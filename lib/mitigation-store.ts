import { useSyncExternalStore } from "react";
import type { WorkflowTask } from "./traffic-workflow";
import type { CongestionResult } from "./congestion-executor";
import { abstreetRuntime } from "./abstreet-runtime";
import { mitigationSteps, type MitigationContext, type Observation, type SignalCandidate, type SignalPlan, type TrialComparison } from "./mitigation";

export type MitigationTask = WorkflowTask & {
  context?: MitigationContext; candidates: SignalCandidate[]; evidence: string; observations: Observation[];
  selectedId?: string; decision?: "keep" | "restore"; comparison?: TrialComparison; round?: string;
  advancedSeconds?: number; targetRoadId?: number; panelOpen: boolean; approvalVersion: number;
  diagnosisObservations?: Observation[];
  preset?: boolean;
  sourceDetection?: CongestionResult;
  originalPlan?: SignalPlan | null; baselineSamples?: Observation[]; candidateSamples?: Observation[];
  liveSignal?: SignalPlan | null; signalError?: string; signalReadAt?: number;
  planApplied?: boolean; previewStage?: number; pauseRequested?: boolean; observationPaused?: boolean; roundDeadline?: number;
  alternativeTargets?: { roadId: number; name?: string; eligible: boolean; reason: string }[];
};
const tasks = new Map<string, MitigationTask>();
const listeners = new Set<() => void>();
const seen = new Set<string>();
const sources = new Map<string, {roadId:number; result:CongestionResult}>();
const recovery = new Set<string>();
export const mitigationStore = {
  get(id: string | null) { return id ? tasks.get(id) ?? null : null; },
  recoveryRequired() { return recovery.size > 0; },
  switchBlocked() { return this.busy() || this.recoveryRequired(); },
  confirmReinitialize() { recovery.clear(); this.emit(); },
  restored(sessionId: string, id: string) {
    if (recovery.delete(`${sessionId}:${id}`)) {
      const task = this.get(sessionId);
      if (task?.id === id) tasks.set(sessionId, { ...task, status: "cancelled", message: "已确认恢复本轮开始状态。", endedAt: Date.now() });
      this.emit();
    }
  },
  attachSource(sessionId: string, id: string, result: CongestionResult) {
    const task = this.get(sessionId);
    if (task?.id === id) { tasks.set(sessionId, { ...task, sourceDetection: structuredClone(result) }); this.emit(); }
  },
  takeSource(sessionId: string) { const source=sources.get(sessionId); sources.delete(sessionId); return source; },
  busy() { return [...tasks.values()].some(t => ["running", "awaiting_selection", "awaiting_decision", "restoring"].includes(t.status)); },
  start(sessionId: string, id: string, toolName: string) {
    if (seen.has(`${sessionId}:${id}`) || this.switchBlocked()) return false;
    seen.add(`${sessionId}:${id}`);
    const startedAt = Date.now();
    tasks.set(sessionId, { sessionId, id, scenarioId: abstreetRuntime.get().scenarioId, runId: abstreetRuntime.get().runId, definition: { kind: "mitigation", title: "拥堵溯源与配时验证", steps: mitigationSteps }, status: "running", stage: 0, startedAt, stageTimes: {0: startedAt}, calls: [{id, name:toolName, kind:"mcp", startedAt}], message:"正在准备目标道路与仿真场景…", candidates:[], evidence:"", observations:[], panelOpen:false, approvalVersion:0 });
    this.emit(); return true;
  },
  update(sessionId: string, id: string, patch: Partial<MitigationTask>) {
    const task = this.get(sessionId);
    if (!task || task.id !== id || ["cancelled", "failed", "completed"].includes(task.status)) return false;
    tasks.set(sessionId, { ...task, ...patch }); this.emit(); return true;
  },
  scope(sessionId: string, id: string) {
    const { scenarioId, runId } = abstreetRuntime.get();
    this.update(sessionId, id, { scenarioId, runId });
  },
  stage(sessionId: string, id: string, stage: number, message: string) {
    const task = this.get(sessionId); if (!task) return;
    this.update(sessionId,id,{stage,message,stageTimes:{...task.stageTimes,[stage]:task.stageTimes?.[stage] ?? Date.now()}});
  },
  trace(sessionId: string, id: string, name: string, kind: "mcp" | "internal", startedAt: number, endedAt?: number, error?: string) {
    const task = this.get(sessionId); if (!task) return;
    const callId = `${name}:${startedAt}`;
    this.update(sessionId,id,{calls:[...task.calls.filter(c=>c.id!==callId && !(kind==="mcp" && c.id===task.id)),{id:callId,name,kind,startedAt,endedAt,error}]});
  },
  end(sessionId: string, id: string, status: "completed" | "failed" | "cancelled", message: string) {
    const task=this.get(sessionId); if(!task)return;
    if (task.id !== id) return;
    if (status === "failed" && message.includes("恢复失败")) recovery.add(`${sessionId}:${id}`);
    const endedAt=Date.now();
    this.update(sessionId,id,{status,message,endedAt,liveSignal:null,signalError:undefined,planApplied:status==="completed"?task.planApplied:false,previewStage:undefined,pauseRequested:false,observationPaused:false,roundDeadline:undefined,panelOpen:status!=="cancelled",calls:task.calls.map(c=>c.endedAt?c:{...c,endedAt,error:status==="completed"?undefined:message})});
  },
  cancel(sessionId: string, message = "任务已取消，正在恢复本轮开始状态…") {
    const task = this.get(sessionId); if (!task || !["running","awaiting_selection","awaiting_decision"].includes(task.status)) return;
    if (task.preset) {
      window.dispatchEvent(new CustomEvent("traffic-cancel-mitigation",{detail:{sessionId,taskId:task.id}}));
      this.end(sessionId,task.id,"cancelled","任务已取消，真实仿真配时和时间未作修改。");
      return;
    }
    this.update(sessionId,task.id,{status:"restoring",message});
    window.dispatchEvent(new CustomEvent("traffic-cancel-mitigation",{detail:{sessionId,taskId:task.id}}));
    const pending=this.get(sessionId);
    if (pending?.id===task.id && pending.status==="restoring" && !pending.context && pending.calls.every(call=>call.kind==="mcp")) {
      this.end(sessionId,task.id,"cancelled","准备任务已取消，尚未修改仿真。");
    }
    void fetch("/api/simulation-demo",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"cancel_detection",sessionId,toolCallId:task.id})}).catch(()=>{});
  },
  panel(sessionId: string, open: boolean) { const task=this.get(sessionId); if(task){tasks.set(sessionId,{...task,panelOpen:open});this.emit();} },
  emit() { for(const listener of listeners) listener(); },
  subscribe(listener:()=>void) {listeners.add(listener);return()=>{listeners.delete(listener);};},
};
export function useMitigationTask(sessionId: string | null) { return useSyncExternalStore(mitigationStore.subscribe,()=>mitigationStore.get(sessionId),()=>null); }

export function startMitigation(sessionId: string | null, roadId?: number, prompt?: string, detection?: CongestionResult, presetScenario = false) {
  const reason = abstreetRuntime.actionReason("analyze_congestion_cause", detection && abstreetRuntime.get().runId ? detection : undefined);
  if (!prompt && (reason || mitigationStore.switchBlocked())) {
    window.dispatchEvent(new CustomEvent("traffic-action-error", { detail: reason || "已有任务或恢复未确认，请先返回当前任务处理。" }));
    return false;
  }
  if (sessionId && !prompt) {
    if (detection && roadId!==undefined && detection.roads.some(road=>road.roadId===roadId)) sources.set(sessionId,{roadId,result:structuredClone(detection)});
    else sources.delete(sessionId);
  }
  const detail = {sessionId,roadId,prompt,presetScenario,handled:false};
  const accepted=window.dispatchEvent(new CustomEvent("traffic-start-mitigation",{detail,cancelable:true})) && detail.handled;
  if (!accepted && sessionId && !prompt) sources.delete(sessionId);
  return accepted;
}
