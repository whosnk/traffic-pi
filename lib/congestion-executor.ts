import { congestionRule, screenCongestion } from "./congestion";

type Presentation = { showRoads: (roadIds: number[]) => Promise<boolean> };

export async function executeCongestion(
  request: (action: string, params?: Record<string, unknown>) => Promise<unknown>,
  progress: (stage: number, message: string) => void,
  signal: AbortSignal,
  presentation?: Presentation,
) {
  async function call(action: string, params?: Record<string, unknown>) {
    signal.throwIfAborted();
    const result = await request(action, params);
    signal.throwIfAborted();
    return result as Record<string, unknown>;
  }
  progress(1, "正在读取当前场景、仿真时间和道路指标…");
  const state = await call("get_simulation_state");
  const stateCollectedAt = new Date().toISOString();
  if (!state || typeof state.paused !== "boolean" || !Number.isFinite(state.speedMultiplier) || !Number.isFinite(state.simulationTime)) throw new Error("数据不足：仿真暂停状态、速度或时间未提供。");
  const metrics = await call("get_road_metrics");
  const metricsCollectedAt = new Date().toISOString();
  progress(2, "正在按排队车辆数和平均车速筛选疑似拥堵道路…");
  const { roads, sampledRoadCount } = screenCongestion(metrics);
  progress(3, roads.length ? "正在替换检测高亮并定位首位道路…" : "未发现符合条件的道路，正在清除上轮高亮…");
  await call("clear_highlights");
  let cameraFocused = false;
  if (roads.length) {
    await call("highlight_roads", { roads: roads.map(({ roadId, level }) => ({ roadId, level })) });
    if (presentation) cameraFocused = await presentation.showRoads(roads.map(road => road.roadId));
    else { await call("focus_on_road", { roadId: roads[0].roadId }); cameraFocused = true; }
  }
  const after = await call("get_simulation_state");
  if (state.paused !== after.paused || state.speedMultiplier !== after.speedMultiplier) throw new Error("检测前后的暂停或速度状态发生变化，请核查控制桥后重试。");
  if (state.paused && state.simulationTime !== after.simulationTime) throw new Error("暂停状态下仿真时间发生变化，本轮检测未通过状态保持检查。");
  return { type: "traffic-pi-congestion", roads, sampledRoadCount, state, metrics, stateCollectedAt, metricsCollectedAt, cameraFocused,
    simulationTime: metrics.simulationTime ?? state.simulationTime, rule: congestionRule,
    message: roads.length ? `在接口返回的 ${sampledRoadCount} 条道路中发现 ${roads.length} 处疑似拥堵，已高亮${cameraFocused ? "并定位首位道路" : "；用户已手动接管视角，可点击结果定位"}。`
      : "当前未发现符合筛选条件的疑似拥堵道路", samplingNote: "仅覆盖接口返回道路，最多展示前 5 处；不代表全路网。车速是历史行程平均，非瞬时测速。状态与道路指标分别采集；运行中的仿真并非完全同一瞬间。" };
}

export type CongestionResult = Awaited<ReturnType<typeof executeCongestion>> & { scenarioId?: string; runId?: string };
