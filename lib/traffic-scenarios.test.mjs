import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const { chongqingScenario, highwayScenario, trafficScenarios, scenarioSwitchReason, abstreetScenarios, sceneIdentityMatches, scenarioActionReason } = await createJiti(import.meta.url).import("./traffic-scenarios.ts");

test("registry separates category, engine and visualization without copying backend metadata", () => {
  const backend = { scenario_id: "four_intersections", name: "后端名称", description: "后端说明", supported_capabilities: ["查询"], intersections: [] };
  const entries = trafficScenarios([backend]);
  assert.equal(new Set(entries.map(item => item.id)).size, entries.length);
  assert.equal(entries[0], chongqingScenario);
  assert.equal(entries[1].name, backend.name);
  assert.equal(entries[1].description, backend.description);
  assert.deepEqual(entries[1].capabilities, backend.supported_capabilities);
  assert.equal(entries[1].category, "urban");
  assert.equal(entries[1].engine, "sumo");
  assert.equal(entries[1].backendId, "four_intersections");
  assert.match(entries[1].availabilityNote, /未验证/);
  assert.equal(highwayScenario.availability, "implemented");
  assert.equal(highwayScenario.entryTarget, "abstreet");
  assert.deepEqual(trafficScenarios([]).map(item => item.id), [chongqingScenario.id, highwayScenario.id]);
});

test("switching blocks execution and pending decisions until explicitly settled", () => {
  assert.match(scenarioSwitchReason({ mitigationBusy: true, detectionBusy: false, agentBusy: false }), /保留／恢复/);
  assert.match(scenarioSwitchReason({ mitigationBusy: false, detectionBusy: true, agentBusy: false }), /检测/);
  assert.match(scenarioSwitchReason({ mitigationBusy: false, detectionBusy: false, agentBusy: true }), /Agent/);
  assert.equal(scenarioSwitchReason({ mitigationBusy: false, detectionBusy: false, agentBusy: false }), "");
});

test("city and highway require distinct actual identities and enforce highway capability limits", () => {
  const [city, highway] = abstreetScenarios;
  assert.notEqual(city.mapPath, highway.mapPath);
  assert.notEqual(city.demandPath, highway.demandPath);
  assert.equal(city.autoPlay, false);
  assert.equal(highway.autoPlay, true);
  assert.equal(sceneIdentityMatches(highway, {map: city.mapPath, scene: city.scene, randomSeed:42}), false);
  assert.equal(sceneIdentityMatches(highway, {map: highway.mapPath, scene: highway.scene, randomSeed:42}), true);
  assert.match(scenarioActionReason(highway.id, "analyze_congestion_cause"), /城市交通/);
  assert.match(scenarioActionReason(highway.id, "apply_signal_plan"), /城市交通/);
  assert.equal(scenarioActionReason(highway.id, "pause"), "");
  assert.equal(scenarioActionReason(city.id, "analyze_congestion_cause"), "");
});

test("failed rollback remains a switch barrier instead of reporting a safe scene", async () => {
  const { mitigationStore } = await createJiti(import.meta.url).import("./mitigation-store.ts");
  mitigationStore.start("rollback-failure", "rollback-task", "analyze_congestion_cause");
  assert.equal(mitigationStore.switchBlocked(), true);
  mitigationStore.end("rollback-failure", "rollback-task", "failed", "恢复失败，请手动核查。");
  assert.equal(mitigationStore.busy(), false);
  assert.equal(mitigationStore.switchBlocked(), true);
  assert.equal(mitigationStore.start("rollback-failure", "replacement", "analyze_congestion_cause"), false);
  mitigationStore.cancel("rollback-failure");
  assert.equal(mitigationStore.recoveryRequired(), true);
  mitigationStore.confirmReinitialize();
  assert.equal(mitigationStore.switchBlocked(), false);
});
