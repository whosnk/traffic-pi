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
  id: "planned:highway", name: "高速公路场景", category: "highway",
  engine: "sumo", visualization: "external",
  description: "尚未建模，也未接入主可视化。",
  source: "待开发", capabilities: [],
  availability: "planned", availabilityNote: "规划中 · 当前不可运行",
  entryTarget: null,
};

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
