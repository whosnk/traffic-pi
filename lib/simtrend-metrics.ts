export function comparisonMetrics(data: Record<string, unknown> | undefined) {
  const before = data?.baseline as Record<string, unknown> | undefined;
  const after = data?.optimized as Record<string, unknown> | undefined;
  if (!before || !after) return [];
  const definitions = [
    ["overall_avg_wait_s", "全路网车辆平均等待", "秒"],
    ["overall_time_loss_s", "全路网车辆平均时间损失", "秒"],
    ["arrived_vehicle_count", "全路网已到达车辆", "辆"],
    ["running_vehicle_count", "结束时仍在路网车辆", "辆"],
    ["target_avg_queue_m", "重点对象平均排队", "米"],
    ["target_avg_wait_s", "重点车流平均等待", "秒"],
  ];
  return definitions.flatMap(([key, label, unit]) => {
    const a = before[key], b = after[key];
    if (typeof a !== "number" || typeof b !== "number" || !Number.isFinite(a) || !Number.isFinite(b)) return [];
    return [{ key, label, unit, before: a, after: b, delta: b - a, max: Math.max(a, b, 1) }];
  });
}
