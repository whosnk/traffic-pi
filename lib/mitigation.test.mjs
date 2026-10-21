import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const jiti=createJiti(import.meta.url);
const {diagnose,summarizeObservations}=await jiti.import("./mitigation.ts");
const {mitigationStore}=await jiti.import("./mitigation-store.ts");
const {MitigationExecutor}=await jiti.import("./mitigation-executor.ts");
const context=()=>({roadId:7,roadName:"目标道路",intersectionId:3,endpoints:[{intersectionId:3,signalised:true,queueVehicles:12}],map:"test",scene:"weekday",randomSeed:42,simulationTime:1000,targetStages:[0],signal:{intersectionId:3,offsetSeconds:0,currentStage:0,stages:[{index:0,durationSeconds:30,minimumSeconds:10,fixed:true,movements:[{fromRoadId:7,toRoadId:8,protected:true,crosswalk:false}]},{index:1,durationSeconds:30,minimumSeconds:20,fixed:true,movements:[]}]},approaches:[{roadId:7,name:"目标道路",toIntersectionId:3,queueVehicles:12,currentWaitingSeconds:50,waitingAtIntersection:3,occupancy:.4,downstreamOccupancy:.2,passedVehicles:10},{roadId:8,name:"交叉方向",toIntersectionId:3,queueVehicles:3,currentWaitingSeconds:5,waitingAtIntersection:1,occupancy:.1,downstreamOccupancy:.1,passedVehicles:3}]});
const samples=(c)=>[0,60,120].map(dt=>({simulationTime:1000+dt,approaches:structuredClone(c.approaches),currentStage:0}));
test("evidence and candidates preserve cycle, pedestrian minimum and original data",()=>{
  const c=context(),before=structuredClone(c),result=diagnose(c,samples(c));
  assert.equal(result.candidates.length,2);
  for(const candidate of result.candidates){assert.equal(candidate.durations.reduce((a,b)=>a+b),60);assert.ok(candidate.durations.every((d,i)=>d>=c.signal.stages[i].minimumSeconds));}
  assert.deepEqual(c,before);
  c.signal.stages[1].minimumSeconds=27;assert.equal(diagnose(c,samples(c)).candidates.length,0);
  c.signal=null;assert.match(diagnose(c,samples(c)).reason,/没有信号/);
});
test("incomplete cycles, adaptive phases, downstream blockage and missing fields never produce executable plans",()=>{
  const c=context();assert.equal(diagnose(c,samples(c).slice(0,2)).candidates.length,0);
  c.signal.stages[0].fixed=false;assert.equal(diagnose(c,samples(c)).candidates.length,0);
  c.signal.stages[0].fixed=true;c.approaches[0].downstreamOccupancy=.95;assert.match(diagnose(c,samples(c)).reason,/下游/);
  c.approaches[0].downstreamOccupancy=undefined;assert.equal(diagnose(c,samples(c)).candidates.length,0);
});
test("comparison uses sampled queue integral and passing count, rejects time regression",()=>{
  const c=context(),s=samples(c);s[1].approaches[0].queueVehicles=6;s[2].approaches[0].queueVehicles=0;s[2].approaches[0].passedVehicles=20;
  const result=summarizeObservations(s)[0];assert.equal(result.meanQueue,6);assert.equal(result.waitingVehicleSeconds,720);assert.equal(result.passedVehicles,10);assert.equal(result.endQueue,0);
  assert.throws(()=>summarizeObservations([s[0],s[0]]),/未推进/);
});

function fixture(){
  let c=context(),paused=true,speed=30;const snapshots=new Map(),calls=[];
  const request=async(action,p={})=>{
    calls.push(action);
    if(action==="get_simulation_state")return {simulationTime:c.simulationTime,paused,speedMultiplier:speed,capabilities:["traffic-pi-mitigation-v1"]};
    if(action==="mitigation_begin"){snapshots.set("origin",{c:structuredClone(c),paused,speed});paused=true;}
    if(action==="mitigation_context")return structuredClone(c);
    if(action==="mitigation_checkpoint")snapshots.set(p.name,{c:structuredClone(c),paused,speed});
    if(action==="mitigation_restore"){c=structuredClone(snapshots.get(p.name).c);paused=true;}
    if(action==="mitigation_cancel" || action==="mitigation_finish"){const saved=snapshots.get(action==="mitigation_cancel"?"origin":p.name),origin=snapshots.get("origin");c=structuredClone(saved.c);paused=origin.paused;speed=origin.speed;}
    if(action==="run_for"){c.simulationTime+=p.durationSeconds;c.approaches[0].passedVehicles++;}
    if(action==="apply_signal_plan")c.signal.stages.forEach((s,i)=>s.durationSeconds=p.stageDurationsSeconds[i]);
    return {valid:true};
  };
  return {request,calls,state:()=>({c,paused,speed})};
}
test("browser commands arriving before SSE start initialize once and preserve existing task ownership",async()=>{
  const f=fixture(),executor=new MitigationExecutor(f.request,async()=>{}),sid="mitigation-before-sse",signal=new AbortController().signal;
  await executor.execute("analyze_congestion_cause",{roadId:7},sid,"browser-first",signal);
  assert.equal(mitigationStore.get(sid).status,"awaiting_selection");
  assert.equal(mitigationStore.start(sid,"browser-first","late-sse"),false);
  await assert.rejects(executor.execute("analyze_congestion_cause",{roadId:8},sid,"second-call",signal),/等待选择/);
  assert.equal(executor.approve(sid,"green-5").taskId,"browser-first");
  await executor.cancel();
  await assert.rejects(executor.execute("analyze_congestion_cause",{roadId:7},sid,"browser-first",signal),/已结束或取消/);
  assert.equal(mitigationStore.get(sid).status,"cancelled");
});

test("user grants, same-start rounds, final restoration and fresh task original state",async()=>{
  const f=fixture(),executor=new MitigationExecutor(f.request,async()=>{},30),sid="mitigation-test";
  mitigationStore.start(sid,"t1","analyze_congestion_cause");
  const signal=new AbortController().signal;
  await executor.execute("analyze_congestion_cause",{roadId:7},sid,"t1",signal);
  const ready=mitigationStore.get(sid);assert.equal(ready.status,"awaiting_selection");assert.equal(ready.candidates.length,2);assert.equal(f.state().paused,true);
  await assert.rejects(executor.execute("evaluate_signal_plan",{taskId:"t1",approvalToken:"made-up",version:1},sid,"call2",signal),/授权/);
  const grant=executor.approve(sid,"green-5");
  await executor.execute("evaluate_signal_plan",grant,sid,"call2",signal);
  assert.equal(mitigationStore.get(sid).status,"awaiting_decision");
  const comparison=mitigationStore.get(sid).comparison;assert.equal(comparison.duration,300);assert.deepEqual(comparison.baseline,comparison.candidate);
  const final=executor.approve(sid,"restore");await executor.execute("finalize_signal_trial",final,sid,"call3",signal);
  assert.equal(mitigationStore.get(sid).status,"completed");assert.equal(f.state().c.simulationTime,1420);assert.equal(f.state().c.signal.stages[0].durationSeconds,30);assert.equal(f.state().speed,30);
});
test("cancelling a waiting choice restores task origin and prevents late approval",async()=>{
  const f=fixture(),executor=new MitigationExecutor(f.request,async()=>{}),sid="mitigation-cancel";
  mitigationStore.start(sid,"t2","analyze_congestion_cause");
  await executor.execute("analyze_congestion_cause",{roadId:7},sid,"t2",new AbortController().signal);
  await executor.cancel();assert.equal(f.state().c.simulationTime,1000);assert.equal(mitigationStore.get(sid).status,"cancelled");assert.throws(()=>executor.approve(sid,"green-5"));
});

test("stale grants, changed plans and keep decision are enforced at execution",async()=>{
  const f=fixture(),executor=new MitigationExecutor(f.request,async()=>{}),sid="mitigation-grants",signal=new AbortController().signal;
  mitigationStore.start(sid,"grants","analyze_congestion_cause");
  await executor.execute("analyze_congestion_cause",{roadId:7},sid,"grants",signal);
  const stale=executor.approve(sid,"green-5"),current=executor.approve(sid,"green-10");
  await assert.rejects(executor.execute("evaluate_signal_plan",stale,sid,"stale",signal),/授权/);
  await assert.rejects(executor.execute("evaluate_signal_plan",current,"wrong-session","wrong",signal),/授权/);
  await executor.execute("evaluate_signal_plan",current,sid,"evaluate",signal);
  assert.equal(mitigationStore.get(sid).comparison.baselineSamples.length,61);
  assert.equal(mitigationStore.get(sid).comparison.candidateSamples.length,61);
  const keep=executor.approve(sid,"keep");await executor.execute("finalize_signal_trial",keep,sid,"keep",signal);
  assert.equal(f.state().c.signal.stages[0].durationSeconds,40);
  assert.equal(f.state().speed,30);
  assert.equal(mitigationStore.get(sid).status,"completed");
  const changed=fixture(),ex=new MitigationExecutor(changed.request,async()=>{}),s2="mitigation-changed";
  mitigationStore.start(s2,"changed","analyze_congestion_cause");await ex.execute("analyze_congestion_cause",{roadId:7},s2,"changed",signal);
  const grant=ex.approve(s2,"green-5");changed.state().c.signal.offsetSeconds=1;
  await assert.rejects(ex.execute("evaluate_signal_plan",grant,s2,"eval-changed",signal),/发生变化/);
  assert.equal(mitigationStore.get(s2).status,"failed");assert.equal(changed.state().c.simulationTime,1000);
});

test("cancel during advancement restores origin; failed restoration never claims success",async()=>{
  const f=fixture();let entered;
  const reached=new Promise(resolve=>entered=resolve);
  const executor=new MitigationExecutor(async(action,params,signal)=>{
    if(action==="run_for"){entered();await new Promise((resolve,reject)=>signal.addEventListener("abort",()=>reject(signal.reason),{once:true}));}
    return f.request(action,params);
  },async()=>{}),sid="mitigation-active-cancel";
  mitigationStore.start(sid,"active","analyze_congestion_cause");
  const running=executor.execute("analyze_congestion_cause",{roadId:7},sid,"active",new AbortController().signal);
  const rejection=assert.rejects(running);
  await reached;await executor.cancel();await rejection;
  assert.equal(mitigationStore.get(sid).status,"cancelled");assert.equal(f.state().c.simulationTime,1000);
  const broken=fixture(),ex=new MitigationExecutor(async(action,params)=>{if(action==="mitigation_cancel")throw new Error("connection lost");return broken.request(action,params);},async()=>{}),s2="mitigation-restore-fail";
  mitigationStore.start(s2,"broken","analyze_congestion_cause");await ex.execute("analyze_congestion_cause",{roadId:7},s2,"broken",new AbortController().signal);
  await ex.cancel();assert.equal(mitigationStore.get(s2).status,"failed");assert.match(mitigationStore.get(s2).message,/恢复失败/);
});
