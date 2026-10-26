import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";

const jiti = createJiti(import.meta.url);
const { trafficResultFromMessage: parse, trafficResultStore: store } = await jiti.import("./traffic-results.ts");
const scene = revision => ({ type: "traffic-pi-geo", revision, sources: [], layers: [] });
const message = (id, toolName, value) => ({ role: "toolResult", toolCallId: id, toolName, content: [{ type: "text", text: JSON.stringify(value) }] });
const metrics = { status: "completed", simulationTime: 28800, result: { roads: [{ roadId: 1, speedKph: 23, queue: null }], units: { speedKph: "km/h" } }, error: null };

test("mitigation snapshots require a valid task envelope and successful phase",()=>{
  for(const tool of ["analyze_congestion_cause","evaluate_signal_plan","finalize_signal_trial"]){
    const data={type:"traffic-pi-mitigation",taskId:"t",status:"awaiting_selection",message:"等待选择",candidates:[]};
    const envelope={status:"completed",result:data};
    assert.equal(parse(message(tool,`mcp_demo_${tool}_abcdef012345`,envelope)).data.taskId,"t");
    assert.equal(parse(message(tool,tool,{...envelope,result:{...data,status:"cancelled"}})),null);
    assert.equal(parse(message(tool,tool,metrics)),null);
  }
});

test("SimTrend completed, failed and clarification results survive MCP envelopes", () => {
  for (const status of ["completed", "failed", "clarification_required"]) {
    const value = { status, result: { type: "simtrend-result", ok: status === "completed", status, scenario_id: "four_intersections" } };
    assert.equal(parse(message(status, "mcp_simtrend_get_simtrend_task_abcdef012345", { structuredContent: value })).type, "simtrend");
    assert.equal(parse(message(status, "read", value)), null);
  }
});

test("recognizes wrapped MCP results and aliased traffic tools", () => {
  const result = parse(message("road-1", "mcp_custom_get_road_metrics_abcdef012345", { content: [{ type: "text", text: JSON.stringify(metrics) }], structuredContent: metrics }));
  assert.equal(result.type, "get_road_metrics");
  assert.deepEqual(result.data, metrics.result);
  assert.equal(result.simulationTime, 28800);
  for (const tool of ["get_intersection_metrics", "capture_metrics", "compare_metrics"]) assert.equal(parse(message(tool, tool, metrics)).type, tool);
});

test("accepts completion details and isolates snapshots from mutable source data", () => {
  const source = structuredClone(metrics);
  const result = parse({ role: "toolResult", toolCallId: "snapshot", toolName: "get_road_metrics", content: [], details: { structuredContent: source } });
  source.result.roads[0].speedKph = 999;
  assert.equal(result.data.roads[0].speedKph, 23);
});

test("retains scene and run identity alongside historical metrics", () => {
  const value = { ...metrics, result: { ...metrics.result, scenarioId: "abstreet:highway-demo", runId: "highway-run" } };
  const result = parse(message("scoped", "get_road_metrics", { structuredContent: value }));
  assert.equal(result.scenarioId, "abstreet:highway-demo");
  assert.equal(result.runId, "highway-run");
  store.add("scoped-history", result);
  store.add("scoped-history", parse(message("new-city", "get_road_metrics", metrics)));
  assert.equal(store.get("scoped-history").results[1].runId, "highway-run");
});

test("ignores failures, unrelated tools, malformed and partial results", () => {
  for (const value of [{ ...metrics, status: "failed" }, { ...metrics, status: "loading" }, { ...metrics, result: null }, { ...metrics, result: [] }, { ...metrics, result: {} }, { isError: true, content: [{ type: "text", text: JSON.stringify(metrics) }] }]) assert.equal(parse(message("invalid", "get_road_metrics", value)), null);
  assert.equal(parse(message("normal", "read", metrics)), null);
  assert.equal(parse({ ...message("error", "get_road_metrics", metrics), isError: true }), null);
  assert.equal(parse(message("geometry", "publish_geo_scene", { ...scene(1), sources: [{ id: "x", data: { type: "FeatureCollection", features: [{ type: "Feature", id: "x", geometry: { type: "Point", coordinates: [999, 999] } }] } }] })), null);
});

test("deduplicates completions, ignores stale scenes and preserves history selection", () => {
  const sid = "history";
  const first = parse(message("geo-1", "publish_geo_scene", scene(1)));
  assert.equal(store.add(sid, first), true);
  assert.equal(store.add(sid, first), false);
  store.select(sid, first.id);
  const second = parse(message("geo-2", "publish_geo_scene", scene(2)));
  assert.equal(store.add(sid, second), true);
  assert.equal(store.get(sid).selectedGeoId, "geo-1");
  assert.equal(store.get(sid).results[0].unread, true);
  assert.equal(store.get(sid).results[1].unread, false);
  assert.equal(store.add(sid, parse(message("stale", "publish_geo_scene", scene(1)))), false);
  assert.equal(store.add(sid, parse(message("equal", "publish_geo_scene", scene(2)))), false);
  assert.equal(store.add(sid, parse(message("older-than-history", "publish_geo_scene", scene(3))), 4), false);
  store.latest(sid);
  assert.equal(store.get(sid).selectedGeoId, null);
  assert.deepEqual(store.get(sid).results.map(item => item.id), ["geo-2", "geo-1"]);
});

test("keeps result lists, unread and expanded selections isolated by session", () => {
  const result = parse(message("same-call", "get_road_metrics", metrics));
  store.add("a", result);
  store.add("b", result);
  store.select("a", result.id);
  assert.equal(store.get("a").expandedId, result.id);
  assert.equal(store.get("a").results[0].unread, false);
  assert.equal(store.get("b").expandedId, null);
  assert.equal(store.get("b").results[0].unread, true);
  assert.deepEqual(store.get(null).results, []);
  assert.deepEqual(store.get("unvisited").results, []);
});

test("metrics details do not change a historical GIS selection", () => {
  store.add("mixed", parse(message("map", "publish_geo_scene", scene(1))));
  store.select("mixed", "map");
  store.add("mixed", parse(message("metric", "get_road_metrics", metrics)));
  store.select("mixed", "metric");
  assert.equal(store.get("mixed").selectedGeoId, "map");
  assert.equal(store.get("mixed").expandedId, "metric");
});
