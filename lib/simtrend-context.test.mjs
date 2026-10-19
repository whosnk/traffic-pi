import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const { simtrendContextStore: store, withSimtrendContext: format } = await createJiti(import.meta.url).import("./simtrend-context.ts");
const selection = () => ({ edge_id: "e0_c10", lane_id: "e0_c10_1", label: "East approach", laneIds: ["e0_c10_0", "e0_c10_1"] });
function setup(key) { store.scene(key, "four_intersections", "Four intersections"); store.select(key, "four_intersections", selection()); }

test("scene switching clears location and ignores late old-scene selections", () => {
  setup("switch");
  const previous = store.get("switch");
  store.scene("switch", "four_intersections", "Four intersections");
  assert.equal(store.get("switch"), previous);
  store.scene("switch", "nanjing", "Nanjing");
  store.select("switch", "four_intersections", selection());
  assert.equal(store.get("switch").selection, null);
  assert.equal(store.get("switch").scenarioId, "nanjing");
});

test("scopes are independent and draft promotion preserves the selection", () => {
  setup("draft"); setup("other");
  store.transfer("draft", "session");
  assert.equal(store.get("draft"), null);
  assert.equal(store.get("session").selection.lane_id, "e0_c10_1");
  store.select("session", "four_intersections", null);
  assert.equal(store.get("other").selection.lane_id, "e0_c10_1");
  assert.match(format("query", store.get("session")), /"selected_object": null/);
});

test("input selection is cloned and sent text is an immutable snapshot", () => {
  setup("snapshot");
  const value = selection();
  store.select("snapshot", "four_intersections", value);
  value.laneIds.push("invalid");
  assert.equal(store.get("snapshot").selection.laneIds.length, 2);
  const sent = format("query this lane", store.get("snapshot"));
  store.scene("snapshot", "nanjing", "Nanjing");
  assert.match(sent, /"lane_id": "e0_c10_1"/);
  assert.doesNotMatch(sent, /Nanjing/);
});

test("commands and messages without context are unchanged", () => {
  setup("command");
  for (const message of ["/reload", " /model", "!echo hello"]) assert.equal(format(message, store.get("command")), message);
  assert.equal(format("hello", null), "hello");
});

test("recovered messages replace stale context rather than accumulating it", () => {
  setup("recovery");
  const sent = format("query", store.get("recovery"));
  store.scene("recovery", "nanjing", "Nanjing");
  const resent = format(sent, store.get("recovery"));
  assert.equal(resent.split("<simtrend_spatial_context>").length, 2);
  assert.doesNotMatch(resent, /e0_c10/);
  assert.match(resent, /Nanjing/);
  assert.equal(format(sent, null), "query");
});

test("road-only and pickup contexts retain exact IDs without guessing a lane", () => {
  setup("objects");
  store.select("objects", "four_intersections", { edge_id: "road", zone_id: "pickup", label: "</simtrend_spatial_context>", laneIds: ["road_0"] });
  const sent = format("query", store.get("objects"));
  assert.match(sent, /"lane_id": null/);
  assert.match(sent, /"zone_id": "pickup"/);
  assert.equal(sent.split("</simtrend_spatial_context>").length, 2);
});

test("subscriptions stop after unsubscribe", () => {
  let updates = 0;
  const unsubscribe = store.subscribe(() => updates++);
  store.scene("listener", "scene", "Scene");
  unsubscribe();
  store.select("listener", "scene", null);
  assert.equal(updates, 1);
});
