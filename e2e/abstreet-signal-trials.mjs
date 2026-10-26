import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import { createJiti } from "jiti";

const { summarizeObservations }=await createJiti(import.meta.url).import("../lib/mitigation.ts");
const browser=await chromium.launch({channel:"msedge"});
let heartbeat;
try {
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errors=[];page.on("pageerror",error=>errors.push(error.message));
  await page.goto("http://127.0.0.1:30141/abstreet/abstreet.html?../data/system/cn/chongqing/scenarios/yuzhong_core/weekday.bin&--time=08:00:00");
  await page.waitForFunction(()=>window.trafficPi?.ready,null,{timeout:180000});
  const request=(action,params={})=>page.evaluate(({action,params})=>window.trafficPi.request(action,params),{action,params});
  const {intersections}=await request("get_intersection_metrics");
  const intersectionId=intersections[0].intersectionId;
  const original=await request("get_signal_plan",{intersectionId});
  const roadId=original.stages.flatMap(stage=>stage.movements).find(movement=>!movement.crosswalk).fromRoadId;
  // Temporary fixed timing in an isolated browser window, never in shipped map resources.
  const durations=original.stages.map(stage=>Math.max(stage.durationSeconds,stage.minimumSeconds));
  await request("apply_signal_plan",{intersectionId,stageDurationsSeconds:durations});
  const leaseId="real-300-second-trials";
  const call=(action,params={})=>request(action,{...params,leaseId});
  const start=await request("get_simulation_state");
  await call("mitigation_begin");
  heartbeat=setInterval(()=>{void call("mitigation_heartbeat").catch(()=>{});},4000);
  await call("set_signal_visualization",{enabled:true,intersectionId});
  await request("focus_on_intersection",{intersectionId,zoom:8,smooth:false});
  await call("mitigation_checkpoint",{name:"validation"});
  const observe=async name=>{
    const samples=[];
    for(let elapsed=0;elapsed<=300;elapsed+=5){
      if(elapsed)await call("run_for",{durationSeconds:5,displaySpeed:5});
      const c=await request("mitigation_context",{roadId,intersectionId});
      samples.push({simulationTime:c.simulationTime,approaches:c.approaches,currentStage:c.signal.currentStage});
      if(elapsed%60===0)console.log(name,elapsed,"/ 300 sim seconds");
    }
    await call("mitigation_checkpoint",{name});
    return samples;
  };
  const baseline=await observe("baseline_end");
  await call("mitigation_restore",{name:"validation"});
  const candidate=[...durations];candidate[0]+=5;candidate[1]-=5;
  await call("mitigation_validate_plan",{intersectionId,stageDurationsSeconds:candidate});
  await call("apply_signal_plan",{intersectionId,stageDurationsSeconds:candidate});
  assert.deepEqual((await request("get_signal_plan",{intersectionId})).stages.map(stage=>stage.durationSeconds),candidate);
  const treatment=await observe("candidate_end");
  assert.equal(baseline.length,61);assert.equal(treatment.length,61);
  assert.deepEqual(treatment.map(sample=>sample.simulationTime),baseline.map(sample=>sample.simulationTime));
  assert.equal(treatment.at(-1).simulationTime-start.simulationTime,300);
  const comparison={baseline:summarizeObservations(baseline),candidate:summarizeObservations(treatment)};
  await call("mitigation_finish",{name:"baseline_end"});
  clearInterval(heartbeat);
  const ended=await request("get_simulation_state");
  assert.equal(ended.simulationTime,start.simulationTime+300);assert.equal(ended.paused,start.paused);assert.equal(ended.speedMultiplier,start.speedMultiplier);
  assert.deepEqual((await request("get_signal_plan",{intersectionId})).stages.map(stage=>stage.durationSeconds),durations);
  assert.deepEqual(errors,[]);
  await writeFile(".next/signal-visual/real-trials.json",JSON.stringify({roadId,intersectionId,durations,candidate,baseline,treatment,comparison},null,2));
  console.log("PASS real 300s + 300s paced trials, same-start 61-sample sequences, apply readback, queue summaries and baseline-end restoration");
}finally{clearInterval(heartbeat);await browser.close();}
