import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { createJiti } from "jiti";

const browser = await chromium.launch({ channel: "msedge" });
try {
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  page.on("pageerror", error=>console.error("PAGE",error.message));
  page.on("console", message=>{if(message.type()==="error")console.error("CONSOLE",message.text());});
  if (process.env.TRAFFIC_PI_CANDIDATE === "1") for (const file of ["game.js", "game_bg.wasm"]) await page.route(`**/wasm_pkg/${file}`, async route => route.fulfill({ body: await readFile(`${process.env.TRAFFIC_PI_CANDIDATE_DIR || ".next/abstreet-mitigation-candidate"}/${file}`), contentType: file.endsWith("wasm") ? "application/wasm" : "text/javascript" }));
  await page.goto("http://127.0.0.1:30141/abstreet/abstreet.html?../data/system/cn/chongqing/scenarios/yuzhong_core/weekday.bin&--time=08:00:00");
  await page.waitForFunction(() => window.trafficPi?.ready, null, { timeout: 180000 });
  const request = async (action, params = {}) => {
    console.log(action,params.name??"");
    return page.evaluate(({action,params}) => window.trafficPi.request(action,params), {action,params});
  };
  const initial = await request("get_simulation_state");
  assert.ok(initial.capabilities.includes("traffic-pi-mitigation-v1"));
  assert.ok(initial.capabilities.includes("traffic-pi-signal-visual-v1"));
  const intersections = await request("get_intersection_metrics");
  const intersectionId = intersections.intersections[0].intersectionId;
  let plan = await request("get_signal_plan", {intersectionId});
  if (plan.stages.some(s=>!s.fixed)) {
    const jiti = createJiti(import.meta.url);
    const { MitigationExecutor } = await jiti.import("../lib/mitigation-executor.ts");
    const roadId = plan.stages.flatMap(s=>s.movements).find(m=>!m.crosswalk).fromRoadId;
    const executor = new MitigationExecutor(request, async roads => { await request("focus_on_road", {roadId:roads[0]}); });
    const diagnosis = await executor.execute("analyze_congestion_cause", {roadId}, "actual-city-diagnosis", "actual-city-call", new AbortController().signal);
    assert.equal(diagnosis.status, "completed");
    assert.equal(diagnosis.candidates.length, 0, "Unsupported shipped signal must not produce a fabricated candidate");
    assert.match(diagnosis.evidence, /自适应|不足|阻塞|信号/);
    assert.equal((await request("get_simulation_state")).simulationTime, initial.simulationTime);
    console.log("PASS unmodified city diagnosis truthfully ends without executable candidates", diagnosis.evidence);
  }
  if(plan.stages.some(s=>!s.fixed)) {
    // A disposable fixed-time fixture exercises validation without changing the shipped scenario.
    await request("apply_signal_plan",{intersectionId,stageDurationsSeconds:plan.stages.map(s=>Math.max(s.durationSeconds,s.minimumSeconds))});
    plan=await request("get_signal_plan",{intersectionId});
  }
  const roadId = plan.stages.flatMap(s=>s.movements).find(m=>!m.crosswalk).fromRoadId;
  const context = await request("mitigation_context", {roadId,intersectionId});
  assert.ok(context.approaches.some(a=>a.roadId===roadId));
  assert.ok(context.signal.stages.every(s=>s.minimumSeconds>=5));
  const leaseId = "real-bridge-test";
  const task = (action,p={})=>request(action,{...p,leaseId});
  await request("set_speed", {speedMultiplier:30});
  await task("mitigation_begin");
  await assert.rejects(request("resume"), /task|lease|locked/i);
  await request("focus_on_intersection",{intersectionId,smooth:false});
  const visual=await task("set_signal_visualization",{enabled:true,intersectionId});
  assert.equal(visual.intersectionId,intersectionId);
  const stable=await request("get_signal_plan",{intersectionId});
  await task("set_signal_visualization",{enabled:true,intersectionId,previewStage:0});
  assert.deepEqual(await request("get_signal_plan",{intersectionId}),stable,"Preview must not change signal or clock");
  await page.screenshot({path:".next/signal-visual/real-signal-preview.png"});
  await task("set_signal_visualization",{enabled:true,intersectionId});
  await request("set_native_ui",{enabled:true,leaseId});
  await request("set_native_ui",{enabled:false,leaseId});
  await task("mitigation_checkpoint",{name:"validation"});
  const replay=async()=>{
    await task("mitigation_restore",{name:"validation"});
    const samples=[];
    for(let i=0;i<3;i++){
      const advancing=task("run_for",{durationSeconds:5,displaySpeed:5});
      await page.waitForTimeout(300);
      const live=await request("get_signal_plan",{intersectionId});
      assert.ok(Number.isFinite(live.stageRemainingSeconds));
      assert.ok(live.simulationTime>=initial.simulationTime);
      await advancing;
      samples.push(await request("mitigation_context",{roadId,intersectionId}));
    }
    return samples;
  };
  const at=Date.now();
  const before=await replay();
  assert.ok(Date.now()-at>=2500,"Paced advancement must be visible rather than instantaneous");
  const after=await replay();
  assert.deepEqual(after,before,"Original versus original must reproduce the same samples");
  await task("mitigation_checkpoint",{name:"baseline_end"});
  await task("mitigation_restore",{name:"validation"});
  const durations=plan.stages.map(s=>s.durationSeconds);
  durations[0]+=5;durations[1]-=5;
  await task("mitigation_validate_plan",{intersectionId,stageDurationsSeconds:durations});
  await task("apply_signal_plan",{intersectionId,stageDurationsSeconds:durations});
  assert.deepEqual((await request("get_signal_plan",{intersectionId})).stages.map(s=>s.durationSeconds),durations);
  await task("run_for",{durationSeconds:15});
  await task("mitigation_checkpoint",{name:"candidate_end"});
  await task("mitigation_finish",{name:"baseline_end"});
  const ended=await request("get_simulation_state");
  assert.equal(ended.simulationTime,initial.simulationTime+15);
  assert.equal(ended.paused,initial.paused);
  assert.equal(ended.speedMultiplier,30);
  assert.deepEqual((await request("get_signal_plan",{intersectionId})).stages.map(s=>s.durationSeconds),plan.stages.map(s=>s.durationSeconds));
  await task("mitigation_begin");
  const advance=task("run_for",{durationSeconds:50,displaySpeed:5}).then(()=>null,error=>String(error));
  await page.waitForTimeout(300);
  await task("mitigation_cancel");
  assert.match(await advance,/cancel/i);
  const cancelled=await request("get_simulation_state");
  assert.equal(cancelled.simulationTime,ended.simulationTime);
  assert.equal(cancelled.paused,ended.paused);
  assert.equal(cancelled.speedMultiplier,ended.speedMultiplier);
  console.log("PASS real Chongqing bridge: topology, pedestrian constraints, lock, paced replay, endpoint restore, active cancellation",{roadId,intersectionId});
} finally { await browser.close(); }
