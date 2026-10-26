import type { SimtrendScenario } from "./simtrend-types";

export type TrafficScenario = {
  id: string;
  name: string;
  category: "urban" | "highway";
  engine: "abstreet" | "sumo";
  visualization: "abstreet" | "sumo-native" | "external";
  description: string;
  source: string;
  capabilities: readonly string[];
  availability: "implemented" | "planned" | "unavailable";
  availabilityNote: string;
  entryTarget: "abstreet" | "sumo" | null;
  backendId?: string;
};

export const chongqingScenario: TrafficScenario = {
  id: "abstreet:chongqing-yuzhong", name: "重庆渝中半岛", category: "urban",
  engine: "abstreet", visualization: "abstreet",
  description: "工作日 08:00 合成交通，固定种子 42；主地图与拥堵治理验证。",
  source: "A/B Street · cn/chongqing/yuzhong_core/weekday.bin",
  capabilities: ["主地图", "拥堵检测", "信号方案验证"],
  availability: "implemented", availabilityNote: "已实现 · 加载后由控制桥确认就绪",
  entryTarget: "abstreet",
};

export const highwayScenario: TrafficScenario = {
  id: "abstreet:highway-demo", name: "典型高速演示", category: "highway",
  engine: "abstreet", visualization: "abstreet",
  description: "双向三车道主线、出入口与立交匝道；固定需求在 A/B Street 中运行。",
  source: "Traffic Pi 合成路网与需求 · 种子 42", capabilities: ["车辆演示", "时间控制", "地图交互"],
  availability: "implemented", availabilityNote: "已接入 · 加载后由控制桥确认地图与需求",
  entryTarget: "abstreet",
};

export const abstreetScenarios = [
  { ...chongqingScenario, label: "城市交通", mapPath: "../data/system/cn/chongqing/maps/yuzhong_core.bin", demandPath: "../data/system/cn/chongqing/scenarios/yuzhong_core/weekday.bin", scene: "weekday", time: "08:00:00", autoPlay: false, endTime: null },
  { ...highwayScenario, label: "高速公路", mapPath: "../data/system/cn/chongqing/maps/highway-demo.bin", demandPath: "../data/system/cn/chongqing/scenarios/highway-demo/motorway.bin", scene: "motorway", time: "08:00:00", autoPlay: true, endTime: 8 * 3600 + 35 * 60 },
] as const;
export type AbstreetScenario = typeof abstreetScenarios[number];
export function abstreetUrl(scenario: AbstreetScenario, standalone = false) {
  return `/abstreet/abstreet.html?${scenario.demandPath}&--time=${scenario.time}${standalone && scenario.autoPlay ? "#autoplay" : ""}`;
}
export function sceneIdentityMatches(scenario: AbstreetScenario, state: { map?: string; scene?: string; randomSeed?: number }) {
  return state.map === scenario.mapPath && state.scene === scenario.scene && state.randomSeed === 42;
}
export function scenarioActionReason(scenarioId: string, action: string) {
  return scenarioId === highwayScenario.id && ["detect_congestion", "analyze_congestion_cause", "evaluate_signal_plan", "finalize_signal_trial", "get_signal_plan", "apply_signal_plan", "restore_signal_plan", "capture_metrics", "compare_metrics"].includes(action)
    ? "典型高速演示仅支持基础播放、时间控制和地图交互；城市拥堵检测与信号配时验证请切换城市交通。" : "";
}

export function trafficScenarios(scenarios: SimtrendScenario[]): TrafficScenario[] {
  return [chongqingScenario, ...scenarios.map((scenario): TrafficScenario => ({
    id: "sumo:" + scenario.scenario_id, backendId: scenario.scenario_id,
    name: scenario.name, category: "urban", engine: "sumo", visualization: "sumo-native",
    description: scenario.description, source: "SimTrend · " + scenario.scenario_id,
    capabilities: scenario.supported_capabilities,
    availability: "implemented", availabilityNote: "已实现 · 可浏览任务；SUMO 运行环境未验证",
    entryTarget: "sumo",
  })), highwayScenario];
}

export function scenarioSwitchReason({ mitigationBusy, detectionBusy, agentBusy }: { mitigationBusy: boolean; detectionBusy: boolean; agentBusy: boolean }) {
  if (mitigationBusy) return "存在未完成的缓解任务。请返回主工作台完成保留／恢复，或取消并确认恢复成功后再切换场景。";
  if (detectionBusy) return "正在检测拥堵。请等待检测结束，或在主工作台取消后再切换场景。";
  if (agentBusy) return "Agent 正在执行。请等待回答结束或主动停止后再切换场景，避免混用道路与任务上下文。";
  return "";
}
