import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const { comparisonMetrics } = await createJiti(import.meta.url).import("./simtrend-metrics.ts");
test("computes actual delta and does not mistake unfinished trips for arrivals", () => {
  const rows = comparisonMetrics({ baseline: { overall_avg_wait_s: 20, arrived_vehicle_count: 13, completed_trip_count: 112 }, optimized: { overall_avg_wait_s: 8, arrived_vehicle_count: 16, completed_trip_count: 120 } });
  assert.equal(rows[0].delta, -12);
  assert.equal(rows[1].before, 13);
  assert.equal(rows[1].delta, 3);
  assert.equal(rows.length, 2);
  assert.deepEqual(comparisonMetrics({ baseline: {}, optimized: {} }), []);
  assert.deepEqual(comparisonMetrics(undefined), []);
});
