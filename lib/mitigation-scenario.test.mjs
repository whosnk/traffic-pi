import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const jiti = createJiti(import.meta.url);
const { MitigationScenario, scenarioContext, scenarioSamples } = await jiti.import("./mitigation-scenario.ts");
const { mitigationStore } = await jiti.import("./mitigation-store.ts");
const { congestionStore } = await jiti.import("./congestion-store.ts");
const { trafficResultStore } = await jiti.import("./traffic-results.ts");
const base = () => ({ roadId: 314, roadName: "目标道路", intersectionId: 201, endpoints: [], signal: null, targetStages: [], simulationTime: 28800, map: "chongqing", scene: "weekday", randomSeed: 42,
  approaches: [314,315].map(roadId => ({ roadId, name: `道路 ${roadId}`, toIntersectionId: 201, queueVehicles: 8, currentWaitingSeconds: 50, waitingAtIntersection: 2, occupancy: .4, downstreamOccupancy: .2, passedVehicles: 10 })) });
function fixture(tick = 0) {
  const calls = [], original = base();
  const scenario = new MitigationScenario(async (action,params) => {
    calls.push({action,params});
    if(action === "get_road_metrics") return { roads: [{roadId:314,queueVehicles:28}] };
    if(action === "mitigation_context") return structuredClone(original);
    return {};
  }, async roads => { calls.push({action:"focus_on_road",params:{roads}}); }, tick);
  return {scenario,calls,original};
}
test("preset context does not mutate topology; both rounds share start and interval, including cross-direction cost", () => {
  const original = base(), context = scenarioContext(original);
  assert.equal(original.signal,null);
  assert.equal(context.signal.stages.reduce((n,s)=>n+s.durationSeconds,0),90);
  const a = scenarioSamples(context), b = scenarioSamples(context,10);
  assert.equal(a.length,61); assert.equal(b.length,61);
  assert.deepEqual(a[0],b[0]);
  assert.equal(a.at(-1).simulationTime,29100);
  assert.ok(b.at(-1).approaches[0].queueVehicles < a.at(-1).approaches[0].queueVehicles);
  assert.ok(b.at(-1).approaches[1].queueVehicles > a.at(-1).approaches[1].queueVehicles);
});
test("preset closes both keep and restore loops without writing real signal, speed or time; results retain provenance", async () => {
  for(const decision of ["keep","restore"]) {
    const sid=`preset-${decision}`, {scenario,calls,original}=fixture();
    await scenario.start(sid);
    assert.equal(mitigationStore.get(sid).status,"awaiting_selection");
    assert.equal(mitigationStore.get(sid).candidates.length,2);
    await assert.rejects(scenario.choose("unknown"));
    await scenario.choose("green-10");
    assert.equal(mitigationStore.get(sid).status,"awaiting_decision");
    await scenario.choose(decision);
    const task=mitigationStore.get(sid);
    assert.equal(task.status,"completed");assert.equal(task.stage,5);assert.equal(task.decision,decision);
    assert.equal(task.context.signal.stages[0].durationSeconds,decision==="keep"?45:35);
    assert.ok(task.calls.every(c=>c.kind==="internal"));
    const results=trafficResultStore.get(sid).results;
    assert.equal(results.length,3); assert.ok(results.every(r=>r.data.preset && r.data.sourceNote));
    assert.equal(trafficResultStore.get(`${sid}-other`).results.length,0);
    assert.ok(calls.every(c=>["get_road_metrics","mitigation_context","highlight_roads","focus_on_road"].includes(c.action)));
    assert.equal(original.signal,null);
    await assert.rejects(scenario.choose("keep"));
  }
});
test("cancel blocks late samples and duplicate selection; failed map operations never report success", async () => {
  const {scenario}=fixture(10),sid="preset-cancel";
  await scenario.start(sid,314);
  const running=scenario.choose("green-5");
  await assert.rejects(scenario.choose("green-5"));
  await scenario.cancel();await assert.rejects(running);
  assert.equal(mitigationStore.get(sid).status,"cancelled");
  assert.equal(trafficResultStore.get(sid).results.length,1);
  const broken=new MitigationScenario(async action=>action==="mitigation_context"?base():{},async()=>{throw new Error("地图不可用");},0);
  await assert.rejects(broken.start("preset-broken",314),/地图不可用/);
  assert.equal(mitigationStore.get("preset-broken").status,"failed");
});
test("SSE-started preset adopts the matching MCP call and rejects canceled replay", async () => {
  const {scenario}=fixture(),sid="preset-sse",id="preset-call";
  assert.equal(mitigationStore.start(sid,id,"analyze_congestion_cause"),true);
  const result=await scenario.start(sid,314,id);
  assert.equal(result.taskId,id);assert.equal(result.preset,true);assert.equal(result.status,"awaiting_selection");
  assert.ok(mitigationStore.get(sid).calls.find(c=>c.kind==="mcp").endedAt);
  await scenario.cancel();
  await assert.rejects(scenario.start(sid,314,id));
  const controller=new AbortController();controller.abort();
  await assert.rejects(scenario.start(sid,314,"new-call",controller.signal));
  assert.equal(mitigationStore.get(sid).status,"cancelled");
});
test("mitigation inherits selected detection identity, queue, clock and an immutable snapshot", async () => {
  const f=fixture(),sid="detection-linked";
  const detection={type:"traffic-pi-congestion",roads:[{roadId:314,name:"检测道路",queueVehicles:23,meanVehicleSpeedKph:2}],simulationTime:28000,metricsCollectedAt:"2026-10-21T01:00:00Z"};
  await f.scenario.start(sid,314,undefined,undefined,detection);
  const task=mitigationStore.get(sid);
  assert.equal(task.targetRoadId,314);
  assert.equal(task.context.simulationTime,28000);
  assert.equal(task.context.approaches[0].queueVehicles,23);
  detection.roads[0].queueVehicles=999;
  assert.equal(task.sourceDetection.roads[0].queueVehicles,23);
  assert.equal(trafficResultStore.get(sid).results[0].data.sourceDetection.roads[0].queueVehicles,23);
  await f.scenario.cancel();
  assert.throws(()=>scenarioContext(base(),{...detection,roads:[{roadId:2,queueVehicles:12}]}),/不匹配/);
});
test("cancel releases an unowned preset or an SSE-only reservation so detection can restart", async () => {
  const previousWindow=globalThis.window,previousCustomEvent=globalThis.CustomEvent,previousFetch=globalThis.fetch;
  globalThis.window=new EventTarget();
  globalThis.CustomEvent=class extends Event{constructor(type,options){super(type);this.detail=options.detail;}};
  globalThis.fetch=async()=>({ok:true});
  try {
    for(const preset of [false,true]) {
      const sid=`orphan-${preset}`;
      assert.equal(mitigationStore.start(sid,"reserved","analyze_congestion_cause"),true);
      if(preset)mitigationStore.update(sid,"reserved",{preset:true,status:"awaiting_selection"});
      assert.equal(congestionStore.start(sid,"blocked"),false);
      mitigationStore.cancel(sid);
      assert.equal(mitigationStore.get(sid).status,"cancelled");
      assert.equal(congestionStore.start(sid,"fresh"),true);
      congestionStore.finish(sid,"fresh");
    }
  } finally {globalThis.window=previousWindow;globalThis.CustomEvent=previousCustomEvent;globalThis.fetch=previousFetch;}
});
