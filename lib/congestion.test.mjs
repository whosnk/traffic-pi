import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const jiti = createJiti(import.meta.url);
const { screenCongestion, isCongestionTool } = await jiti.import("./congestion.ts");
const { executeCongestion } = await jiti.import("./congestion-executor.ts");
const { congestionStore: store } = await jiti.import("./congestion-store.ts");
const { trafficResultFromMessage } = await jiti.import("./traffic-results.ts");
const road = (roadId, queueVehicles, meanVehicleSpeedKph) => ({ roadId, queueVehicles, meanVehicleSpeedKph });
test("thresholds, severity, sorting and five road limit", () => {
  const result = screenCongestion({ roads: [road(1, 5, 10), road(2, 4, 0), road(3, 10, 5), road(4, 20, 3), road(5, 5, 11), road(6, 10, 4), road(7, 8, 8), road(8, 7, 7)] });
  assert.deepEqual(result.roads.map(r => [r.roadId, r.level]), [[4, "critical"], [6, "severe"], [3, "severe"], [7, "warning"], [8, "warning"]]);
  assert.equal(result.sampledRoadCount, 8);
});
test("missing or empty data cannot be reported as no congestion", () => {
  for (const metrics of [null, {}, { roads: [] }, { roads: [road(1, null, 5)] }, { roads: [road(1, 5, undefined)] }, { roads: [road(-1, 5, 1)] }, { roads: [road(1, NaN, 5)] }]) assert.throws(() => screenCongestion(metrics), /数据不足/);
  assert.deepEqual(screenCongestion({ roads: [road(1, 4, 10)] }).roads, []);
});
function mock(roads, failure) {
  const calls = [];
  const state = { paused: true, speedMultiplier: 5, simulationTime: 28800, scene: "weekday" };
  return { calls, request: async (action, params) => {
    calls.push([action, params]);
    if (action === failure) throw new Error("bridge failed");
    return action === "get_road_metrics" ? { roads, simulationTime: 28800 } : state;
  } };
}
test("executor only reads, replaces highlights and focuses after screening", async () => {
  const bridge = mock([road(1, 5, 10)]);
  const stages = [];
  const result = await executeCongestion(bridge.request, s => stages.push(s), new AbortController().signal);
  assert.deepEqual(bridge.calls.map(c => c[0]), ["get_simulation_state", "get_road_metrics", "clear_highlights", "highlight_roads", "focus_on_road", "get_simulation_state"]);
  assert.deepEqual(stages, [1, 2, 3]);
  assert.equal(result.roads[0].roadId, 1);
  assert.equal(result.state.speedMultiplier, 5);
});
test("empty valid result clears highlights without moving camera; failures never complete", async () => {
  const bridge = mock([road(1, 0, 30)]);
  assert.match((await executeCongestion(bridge.request, () => {}, new AbortController().signal)).message, /未发现/);
  assert.deepEqual(bridge.calls.map(c => c[0]), ["get_simulation_state", "get_road_metrics", "clear_highlights", "get_simulation_state"]);
  for (const failure of ["highlight_roads", "focus_on_road"]) await assert.rejects(executeCongestion(mock([road(1, 5, 10)], failure).request, () => {}, new AbortController().signal), /bridge failed/);
});
test("abort prevents later highlighting or focusing", async () => {
  const controller = new AbortController();
  const bridge = mock([road(1, 5, 10)]);
  await assert.rejects(executeCongestion(bridge.request, stage => { if (stage === 2) controller.abort(); }, controller.signal));
  assert.deepEqual(bridge.calls.map(c => c[0]), ["get_simulation_state", "get_road_metrics"]);
});

test("presentation failure never yields a completed detection", async () => {
  await assert.rejects(executeCongestion(mock([road(1, 5, 10)]).request, () => {}, new AbortController().signal, { showRoads: async () => { throw new Error("镜头接口失败"); } }), /镜头接口失败/);
});
test("store isolates sessions, rejects duplicate and late events, retry is a fresh call", () => {
  store.start("a", "one"); store.progress("a", "one", 2, "分析");
  assert.equal(store.start("b", "parallel"), false);
  assert.equal(store.start("a", "one"), false);
  store.progress("a", "one", 1, "迟到"); assert.equal(store.get("a").stage, 2);
  store.finish("a", "one", "停止"); store.progress("a", "one", 3, "迟到");
  assert.equal(store.get("a").status, "failed");
  store.start("b", "one"); store.finish("b", "one");
  store.start("a", "two"); store.finish("a", "one");
  assert.equal(store.get("a").id, "two"); assert.equal(store.get("a").status, "running");
  assert.equal(store.get("b").status, "completed");
});
test("MCP envelope accepts detection results but rejects incomplete data", async () => {
  const data = await executeCongestion(mock([road(1, 5, 10)]).request, () => {}, new AbortController().signal);
  const message = result => ({ role: "toolResult", toolCallId: "one", toolName: "mcp_traffic-demo_detect_congestion_abcdef012345", content: [], details: { structuredContent: { status: "completed", result } } });
  assert.equal(trafficResultFromMessage(message(data)).type, "detect_congestion");
  assert.equal(trafficResultFromMessage(message({})), null);
  assert.equal(isCongestionTool(message(data).toolName), true);
  assert.equal(isCongestionTool("read"), false);
});
