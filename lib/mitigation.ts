export type Approach = {
  roadId: number; name: string; toIntersectionId: number; queueVehicles: number;
  currentWaitingSeconds: number; waitingAtIntersection: number; occupancy: number;
  downstreamOccupancy: number; passedVehicles: number;
};
export type SignalPlan = {
  intersectionId: number; offsetSeconds: number; currentStage: number;
  stages: { index: number; durationSeconds: number; minimumSeconds: number; fixed: boolean;
    movements: { fromRoadId: number; toRoadId: number; crosswalk: boolean; protected: boolean }[] }[];
};
export type MitigationContext = {
  roadId: number; roadName: string; intersectionId: number; targetStages: number[];
  endpoints: { intersectionId: number; signalised: boolean; queueVehicles: number }[];
  approaches: Approach[]; signal: SignalPlan | null; simulationTime: number;
  map: string; scene: string; randomSeed: number;
};
export type SignalCandidate = { id: string; title: string; intersectionId: number; durations: number[]; reason: string; impact: string };
export type Observation = { simulationTime: number; approaches: Approach[]; currentStage: number | null };
export type ApproachSummary = { roadId: number; name: string; meanQueue: number; maxQueue: number; waitingVehicleSeconds: number; passedVehicles: number; endQueue: number };
export type TrialComparison = { baseline: ApproachSummary[]; candidate: ApproachSummary[]; baselineSamples: Observation[]; candidateSamples: Observation[]; startTime: number; duration: number; selected: SignalCandidate; message: string };
export const mitigationSteps = ["确认目标", "拥堵溯源", "选择方案", "基准验证", "方案验证", "效果对比"];
export const mitigationTools = ["analyze_congestion_cause", "evaluate_signal_plan", "finalize_signal_trial"] as const;
export function mitigationTool(name: string) { return mitigationTools.find(tool => name === tool || new RegExp(`^mcp_.+_${tool}_[a-f0-9]{12}$`).test(name)); }

export function diagnose(context: MitigationContext, samples: Observation[]) {
  const target = samples.map(s => s.approaches.find(a => a.roadId === context.roadId)).filter((a): a is Approach => !!a);
  if (!context.signal) return { reason: "目标方向连接的路口没有信号控制，本轮不能通过配时调整。", candidates: [] };
  if (context.signal.stages.some(stage => !stage.fixed)) return { reason: "该路口包含自适应相位，本轮不转换为固定配时。", candidates: [] };
  if (!context.targetStages.length) return { reason: "没有找到为目标方向提供保护放行的相位，证据不足。", candidates: [] };
  if (!target.length || !target.every(a => [a.queueVehicles, a.waitingAtIntersection, a.downstreamOccupancy].every(Number.isFinite))) return { reason: "缺少目标方向的有效等待与下游数据，证据不足。", candidates: [] };
  const cycle = context.signal.stages.reduce((sum, stage) => sum + stage.durationSeconds, 0);
  const observed = (samples.at(-1)?.simulationTime ?? 0) - (samples[0]?.simulationTime ?? 0);
  if (observed + .01 < cycle * 2) return { reason: "观察时间未覆盖两个完整信号周期，不能可靠判断配时不足。", candidates: [] };
  if (target.filter(a => a.downstreamOccupancy >= .85).length > target.length / 2) return { reason: "可能存在下游空间不足：多数采样的下游车道占用达到 85%。增加上游绿灯可能加重阻塞。", candidates: [] };
  if (target.filter(a => a.queueVehicles >= 5 && a.waitingAtIntersection > 0).length < Math.ceil(target.length / 3)) return { reason: "观察到的持续排队或路口等待不足，尚不能归因为信号放行时间不足。", candidates: [] };
  const candidates: SignalCandidate[] = [];
  const stages = context.signal.stages;
  const receiving = context.targetStages.filter(index => stages[index]?.fixed);
  for (const seconds of [5, 10]) {
    const durations = stages.map(stage => stage.durationSeconds);
    const donors = stages.map((stage, index) => ({ index, spare: Math.max(0, Math.floor(stage.durationSeconds - Math.max(5, stage.minimumSeconds))) }))
      .filter(stage => !receiving.includes(stage.index)).sort((a,b) => b.spare - a.spare || a.index - b.index);
    if (!receiving.length || donors.reduce((sum, stage) => sum + stage.spare, 0) < seconds || receiving.some(index => durations[index] + Math.ceil(seconds / receiving.length) > 300)) continue;
    for (let remaining = seconds, n = 0; remaining > 0; n++) { durations[receiving[n % receiving.length]]++; remaining--; }
    let remaining = seconds;
    for (const donor of donors) { const take = Math.min(remaining, donor.spare); durations[donor.index] -= take; remaining -= take; }
    candidates.push({ id: `green-${seconds}`, title: seconds === 5 ? "小幅调整" : "目标方向优先", intersectionId: context.intersectionId, durations,
      reason: `目标方向保护放行相位合计增加 ${seconds} 秒，周期总长与 offset 保持不变。`, impact: "其他相位可用时间减少，可能增加交叉方向排队；需要同起点验证。" });
  }
  return { reason: candidates.length ? "可能存在目标方向放行时间不足：两个周期内持续出现排队及路口等待，下游未持续接近满载。单次观察尚不能证明唯一原因。" : "相位可调整余量不足，无法在保持周期与行人通行时间的前提下生成不同方案。", candidates };
}

export function summarizeObservations(samples: Observation[]): ApproachSummary[] {
  if (samples.length < 2) throw new Error("验证采样不足，不能比较。");
  const first = samples[0], last = samples.at(-1)!;
  const duration = last.simulationTime - first.simulationTime;
  if (!(duration > 0)) throw new Error("验证时间未推进。");
  return first.approaches.map(approach => {
    let integral = 0, maxQueue = 0;
    for (let i = 0; i < samples.length; i++) {
      const value = samples[i].approaches.find(a => a.roadId === approach.roadId);
      if (!value || !Number.isFinite(value.queueVehicles)) throw new Error("验证指标缺失。");
      maxQueue = Math.max(maxQueue, value.queueVehicles);
      if (i) {
        const previous = samples[i-1].approaches.find(a => a.roadId === approach.roadId)!;
        const delta = samples[i].simulationTime - samples[i-1].simulationTime;
        if (!(delta > 0)) throw new Error("验证采样时间顺序错误。");
        integral += (previous.queueVehicles + value.queueVehicles) / 2 * delta;
      }
    }
    const end = last.approaches.find(a => a.roadId === approach.roadId)!;
    if (end.passedVehicles < approach.passedVehicles) throw new Error("通过车辆累计计数发生回退。");
    return { roadId: approach.roadId, name: approach.name, meanQueue: integral / duration, maxQueue, waitingVehicleSeconds: integral, passedVehicles: end.passedVehicles - approach.passedVehicles, endQueue: end.queueVehicles };
  });
}
