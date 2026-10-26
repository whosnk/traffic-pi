export const congestionRule = "启发式筛选：排队 ≥ 5 辆且历史平均车速 ≤ 10 km/h；未经标定。";

export type CongestedRoad = {
  roadId: number;
  name?: string;
  queueVehicles: number;
  meanVehicleSpeedKph: number;
  meanVehicleDelaySeconds?: number;
  level: "warning" | "severe" | "critical";
};

export function screenCongestion(metrics: unknown) {
  const roads = (metrics as { roads?: unknown[] } | null)?.roads;
  if (!Array.isArray(roads) || !roads.length) throw new Error("数据不足：未返回可检测的道路指标。");
  const valid: CongestedRoad[] = [];
  for (const value of roads) {
    const road = value as CongestedRoad;
    if (!road || !Number.isInteger(road.roadId) || road.roadId < 0
      || !Number.isFinite(road.queueVehicles) || road.queueVehicles < 0
      || !Number.isFinite(road.meanVehicleSpeedKph) || road.meanVehicleSpeedKph < 0) {
      throw new Error("数据不足：道路 ID、排队车辆数或平均车速缺失，无法判定拥堵。");
    }
    if (road.queueVehicles >= 5 && road.meanVehicleSpeedKph <= 10) valid.push({ ...road,
      level: road.queueVehicles >= 20 && road.meanVehicleSpeedKph <= 3 ? "critical"
        : road.queueVehicles >= 10 && road.meanVehicleSpeedKph <= 5 ? "severe" : "warning" });
  }
  return { roads: valid.sort((a, b) => b.queueVehicles - a.queueVehicles || a.meanVehicleSpeedKph - b.meanVehicleSpeedKph || a.roadId - b.roadId).slice(0, 5), sampledRoadCount: roads.length };
}

export const congestionSteps = ["准备场景", "读取路况", "识别拥堵", "地图标注", "结果就绪"];
export function isCongestionTool(name: string) {
  return name === "detect_congestion" || /^mcp_.+_detect_congestion_[a-f0-9]{12}$/.test(name);
}

export function congestionError(value: unknown, depth = 0): string {
  if (depth > 8 || value == null) return "";
  if (typeof value === "string") {
    try { return congestionError(JSON.parse(value), depth + 1); } catch { return value; }
  }
  if (Array.isArray(value)) return value.map(item => congestionError(item, depth + 1)).filter(Boolean).join("；");
  if (typeof value !== "object") return "";
  const data = value as Record<string, unknown>;
  for (const key of ["error", "structuredContent", "details", "content", "text"]) {
    const message = congestionError(data[key], depth + 1);
    if (message) return message;
  }
  return "";
}
