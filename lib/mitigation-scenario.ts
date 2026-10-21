import { diagnose, summarizeObservations, type MitigationContext, type Observation } from "./mitigation";
import { mitigationStore } from "./mitigation-store";
import { trafficResultStore, type TrafficResult } from "./traffic-results";
import type { CongestionResult } from "./congestion-executor";

type Request = (action: string, params?: Record<string, unknown>, signal?: AbortSignal) => Promise<unknown>;
const sourceNote = "基于预设信控、需求及放行参数推演；不代表当前 A/B Street 路口实测效果，未写入其真实配时。";

export function scenarioContext(base: MitigationContext, detection?: CongestionResult): MitigationContext {
  const context = structuredClone(base);
  const detected = detection?.roads.find(road=>road.roadId===base.roadId);
  if (detected?.name) context.roadName=detected.name;
  const targetQueue = detected?.queueVehicles ?? base.approaches.find(a=>a.roadId===base.roadId)?.queueVehicles ?? 0;
  if (!Number.isFinite(targetQueue) || targetQueue < 0) throw new Error("缺少有效的目标道路排队指标，请重新检测。");
  if (detection && !detected) throw new Error("检测结果与目标道路不匹配，请重新选择。");
  if (detection) context.simulationTime = Number(detection.simulationTime);
  if (!Number.isFinite(context.simulationTime)) throw new Error("检测结果缺少有效仿真时刻。");
  context.targetStages = [0];
  context.signal = { intersectionId: base.intersectionId, offsetSeconds: 0, currentStage: 0, stages: [
    { index: 0, durationSeconds: 35, minimumSeconds: 15, fixed: true, movements: [{ fromRoadId: base.roadId, toRoadId: base.roadId, crosswalk: false, protected: true }] },
    { index: 1, durationSeconds: 55, minimumSeconds: 25, fixed: true, movements: [] },
  ] };
  context.approaches = base.approaches.map(approach => ({ ...approach,
    queueVehicles: approach.roadId === base.roadId ? targetQueue : approach.queueVehicles,
    waitingAtIntersection: approach.roadId === base.roadId ? Math.round(targetQueue*.65) : approach.waitingAtIntersection,
    currentWaitingSeconds: approach.roadId === base.roadId ? targetQueue*20 : approach.currentWaitingSeconds,
    occupancy: approach.roadId === base.roadId ? .7 : .2, downstreamOccupancy: .3, passedVehicles: 0,
  }));
  if (!context.approaches.some(a => a.roadId === base.roadId)) throw new Error("目标道路缺少有效行驶方向，请重新选择道路。");
  const cross = context.approaches.find(a => a.roadId !== base.roadId);
  if (cross) context.signal.stages[1].movements.push({ fromRoadId: cross.roadId, toRoadId: cross.roadId, crosswalk: false, protected: true });
  return context;
}

export function scenarioSamples(context: MitigationContext, extraGreenSeconds = 0): Observation[] {
  return Array.from({ length: 61 }, (_, index) => {
    const seconds = index * 5;
    return { simulationTime: context.simulationTime + seconds, currentStage: seconds % 90 < 35 + extraGreenSeconds ? 0 : 1,
      approaches: context.approaches.map(approach => {
        const target = approach.roadId === context.roadId;
        const arrivalRate = target ? .45 : .18;
        const serviceRate = target ? .43 + extraGreenSeconds * .009 : .18 - extraGreenSeconds * .002;
        const queueVehicles = Math.max(0, Math.round(approach.queueVehicles + (arrivalRate - serviceRate) * seconds));
        return { ...approach, queueVehicles, waitingAtIntersection: Math.round(queueVehicles * .65),
          currentWaitingSeconds: queueVehicles * 20, passedVehicles: Math.floor(Math.min(serviceRate * seconds, approach.queueVehicles + arrivalRate * seconds)) };
      }) };
  });
}

export class MitigationScenario {
  private sessionId = "";
  private id = "";
  private controller: AbortController | null = null;
  private running = false;
  constructor(private request: Request, private show: (roadIds: number[], signal: AbortSignal) => Promise<void>, private tickMs = 250) {}

  private async wait() {
    const signal = this.controller!.signal;
    signal.throwIfAborted();
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(signal.reason); };
      const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, this.tickMs);
      signal.addEventListener("abort", abort, { once: true });
    });
    signal.throwIfAborted();
  }

  private publish(type: TrafficResult["type"]) {
    const task = mitigationStore.get(this.sessionId)!;
    trafficResultStore.add(this.sessionId, { id: `${this.id}:${type}`, type, title: type === "analyze_congestion_cause" ? "拥堵治理 · 候选方案" : type === "evaluate_signal_plan" ? "拥堵治理 · 推演对比" : "拥堵治理 · 决策结果",
      receivedAt: Date.now(), toolName: "预设场景推演", unread: true, data: { type: "traffic-pi-mitigation", taskId: this.id, preset: true,
        roadId: task.targetRoadId, simulationTime: task.context?.simulationTime, status: task.status, message: task.message,
        evidence: task.evidence, comparison: task.comparison, candidates: task.candidates, sourceDetection:task.sourceDetection, sourceNote } });
  }

  async start(sessionId: string, roadId?: number, callId?: string, signal?: AbortSignal, detection?: CongestionResult) {
    signal?.throwIfAborted();
    const pending = mitigationStore.get(sessionId);
    const ownPending = !!callId && pending?.id === callId && pending.status === "running" && !pending.preset;
    if (this.running || (mitigationStore.busy() && !ownPending)) throw new Error("请先完成或取消当前任务，再开始新的推演。");
    this.sessionId = sessionId; this.id = callId ?? crypto.randomUUID();
    if (!ownPending && !mitigationStore.start(sessionId, this.id, callId?"analyze_congestion_cause":"拥堵治理推演")) throw new Error("当前有其他任务正在执行。");
    this.controller = new AbortController(); this.running = true;
    const abort=()=>{void this.cancel();};
    signal?.addEventListener("abort",abort,{once:true});
    mitigationStore.update(sessionId, this.id, { preset: true, calls: callId?mitigationStore.get(sessionId)!.calls:[], definition: { ...mitigationStore.get(sessionId)!.definition, title: "拥堵溯源与配时验证" } });
    const startedAt = Date.now();
    mitigationStore.trace(sessionId, this.id, "载入预设治理场景", "internal", startedAt);
    try {
      if (roadId === undefined && detection?.roads.length) roadId=detection.roads[0].roadId;
      if (roadId === undefined) {
        const metrics = await this.request("get_road_metrics", {}, this.controller.signal) as { roads?: { roadId: number; queueVehicles: number }[] };
        roadId = [...(metrics.roads ?? [])].sort((a,b) => b.queueVehicles-a.queueVehicles)[0]?.roadId;
      }
      if (!Number.isInteger(roadId)) throw new Error("未找到可定位的道路，请先加载地图。");
      const base = await this.request("mitigation_context", { roadId }, this.controller.signal) as MitigationContext;
      this.controller.signal.throwIfAborted();
      const source = detection?.roads.some(road=>road.roadId===roadId)?detection:undefined;
      const context = scenarioContext(base,source);
      mitigationStore.update(sessionId, this.id, { targetRoadId: roadId, context, sourceDetection:source?structuredClone(source):undefined });
      await this.show([roadId!], this.controller.signal);
      mitigationStore.stage(sessionId, this.id, 1, "正在分析目标方向需求、放行时长与下游空间…");
      await this.request("highlight_roads", { roads: [{ roadId, level: "critical" }] }, this.controller.signal);
      await this.wait();
      const observations = [0,90,180].map(seconds => ({ simulationTime: context.simulationTime + seconds, currentStage: 0, approaches: structuredClone(context.approaches) }));
      const diagnosis = diagnose(context, observations);
      if (!diagnosis.candidates.length) throw new Error("目标道路没有足够的持续排队证据，请重新检测并选择拥堵道路。");
      mitigationStore.update(sessionId, this.id, { evidence: "预设场景中，目标方向需求超过当前绿灯放行能力，排队持续积累；下游空间充足。可通过重新分配绿灯时间进行方案推演。", observations, diagnosisObservations: observations, candidates: diagnosis.candidates });
      await this.wait();
      mitigationStore.trace(sessionId, this.id, "载入预设治理场景", "internal", startedAt, Date.now());
      if (callId) mitigationStore.update(sessionId, this.id, { calls: mitigationStore.get(sessionId)!.calls.map(call=>call.kind==="mcp"?{...call,endedAt:Date.now()}:call) });
      mitigationStore.stage(sessionId, this.id, 2, "已生成两个候选方案，等待选择。");
      mitigationStore.update(sessionId, this.id, { status: "awaiting_selection", panelOpen: true });
      if (!callId) this.publish("analyze_congestion_cause");
      const task = mitigationStore.get(sessionId)!;
      return { type: "traffic-pi-mitigation", taskId: this.id, preset: true, status: task.status, roadId: task.targetRoadId,
        simulationTime: task.context?.simulationTime, message: task.message, evidence: task.evidence, candidates: task.candidates, sourceDetection:task.sourceDetection, sourceNote };
    } catch (error) {
      if (!this.controller.signal.aborted) mitigationStore.end(sessionId, this.id, "failed", String(error));
      throw error;
    } finally { signal?.removeEventListener("abort",abort); this.running = false; }
  }

  async choose(choice: string) {
    const task = mitigationStore.get(this.sessionId);
    if (!task?.preset || task.id !== this.id || this.running) throw new Error("当前推演尚未准备好或正在运行。");
    if (task.status === "awaiting_decision") {
      if (!["keep", "restore"].includes(choice)) throw new Error("请选择保留或恢复。");
      this.running = true;
      try {
        const samples = choice === "keep" ? task.comparison!.candidateSamples : task.comparison!.baselineSamples;
        const last = samples.at(-1)!;
        await this.request("highlight_roads", { roads: [{ roadId: task.targetRoadId, level: choice === "keep" ? "warning" : "critical" }] }, this.controller!.signal);
        this.controller!.signal.throwIfAborted();
        if (mitigationStore.get(this.sessionId)?.id !== this.id || mitigationStore.get(this.sessionId)?.status !== "awaiting_decision") throw new Error("任务已取消，请重新开始。");
        const context = structuredClone(task.context!);
        if (choice === "keep") context.signal!.stages.forEach((stage,index)=>{stage.durationSeconds=task.comparison!.selected.durations[index];});
        mitigationStore.update(this.sessionId, this.id, { decision: choice as "keep" | "restore", context: { ...context, simulationTime: last.simulationTime, approaches: last.approaches }, observations: samples });
        mitigationStore.end(this.sessionId, this.id, "completed", choice === "keep" ? "已保留所选配时的推演结果，治理闭环完成。" : "已恢复原配时的推演结果，治理闭环完成。");
        this.publish("finalize_signal_trial");
        return;
      } finally { this.running = false; }
    }
    if (task.status !== "awaiting_selection") throw new Error("当前阶段不能选择方案。");
    const candidate = task.candidates.find(c => c.id === choice);
    if (!candidate) throw new Error("方案已失效，请重新选择。");
    this.running = true;
    mitigationStore.update(this.sessionId, this.id, { status: "running", panelOpen: false, selectedId: choice });
    const context = structuredClone(task.context!);
    const baseline = scenarioSamples(context), treatment = scenarioSamples(context, candidate.durations[0] - context.signal!.stages[0].durationSeconds);
    try {
      for (const [round, samples, stage] of [["原配时推演", baseline, 3], ["所选方案推演", treatment, 4]] as const) {
        mitigationStore.stage(this.sessionId, this.id, stage, round);
        const at = Date.now(); mitigationStore.trace(this.sessionId, this.id, round, "internal", at);
        await this.show([context.roadId], this.controller!.signal);
        for (let index = 0; index < samples.length; index++) {
          await this.wait();
          const sample = samples[index];
          mitigationStore.update(this.sessionId, this.id, { round, advancedSeconds: index * 5, observations: samples.slice(0, index + 1), context: { ...context, simulationTime: sample.simulationTime, approaches: sample.approaches }, message: `${round} · 已推演 ${index * 5} / 300 秒 · 当前排队 ${sample.approaches.find(a => a.roadId === context.roadId)!.queueVehicles} 辆` });
          if (index % 10 === 0) await this.request("highlight_roads", { roads: [{ roadId: context.roadId, level: sample.approaches.find(a => a.roadId === context.roadId)!.queueVehicles >= 20 ? "critical" : "warning" }] }, this.controller!.signal);
        }
        mitigationStore.trace(this.sessionId, this.id, round, "internal", at, Date.now());
      }
      const comparison = { baseline: summarizeObservations(baseline), candidate: summarizeObservations(treatment), baselineSamples: baseline, candidateSamples: treatment, startTime: context.simulationTime, duration: 300, selected: candidate, message: "目标方向排队减少，同时交叉方向等待增加，请结合两者选择保留或恢复。" };
      mitigationStore.stage(this.sessionId, this.id, 5, "两轮推演完成，等待你决定保留或恢复。");
      mitigationStore.update(this.sessionId, this.id, { comparison, status: "awaiting_decision", panelOpen: true });
      this.publish("evaluate_signal_plan");
    } catch (error) {
      if (!this.controller?.signal.aborted) mitigationStore.end(this.sessionId, this.id, "failed", String(error));
      throw error;
    } finally { this.running = false; }
  }

  async cancel() {
    const task = mitigationStore.get(this.sessionId);
    if (task?.id !== this.id || !task.preset || ["completed", "cancelled", "failed"].includes(task.status)) return;
    this.controller?.abort(new Error("推演已取消。"));
    mitigationStore.end(this.sessionId, this.id, "cancelled", "推演已取消，真实仿真配时和时间未作修改。");
  }
}
