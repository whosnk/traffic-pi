import { diagnose, summarizeObservations, type MitigationContext, type Observation, type SignalPlan } from "./mitigation";
import { mitigationStore } from "./mitigation-store";
import { screenCongestion } from "./congestion";
import type { CongestionResult } from "./congestion-executor";

type Request = (action: string, params?: Record<string, unknown>, signal?: AbortSignal) => Promise<unknown>;
export class MitigationExecutor {
  private sessionId = "";
  private taskId = "";
  private controller: AbortController | null = null;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private locked = false;
  private cancelling: Promise<void> | null = null;
  private approval: { token: string; choice: string; version: number } | null = null;
  private running = false;
  constructor(private raw: Request, private show: (roadIds: number[], signal: AbortSignal) => Promise<void>, private displaySpeed = 5) {}

  approve(sessionId: string, choice: string) {
    const task = mitigationStore.get(sessionId);
    if (!task || task.id !== this.taskId || task.sessionId !== this.sessionId || this.running) throw new Error("任务尚未准备好或正在执行。");
    if (task.status === "awaiting_selection" ? !task.candidates.some(c=>c.id===choice) : task.status !== "awaiting_decision" || !["keep","restore"].includes(choice)) throw new Error("该选择不适用于当前任务。");
    const token = crypto.randomUUID(), version = task.approvalVersion + 1;
    this.approval = {token,choice,version};
    mitigationStore.update(sessionId,task.id,{approvalVersion:version,selectedId:task.status==="awaiting_selection"?choice:task.selectedId,decision:task.status==="awaiting_decision"?choice as "keep"|"restore":undefined});
    return {taskId:task.id,approvalToken:token,version};
  }

  private async request(action: string, params: Record<string, unknown> = {}, signal = this.controller?.signal) {
    signal?.throwIfAborted();
    const at = Date.now();
    mitigationStore.trace(this.sessionId,this.taskId,action,"internal",at);
    try {
      const value = await this.raw(action,{...params,leaseId:this.taskId},signal);
      signal?.throwIfAborted();
      mitigationStore.trace(this.sessionId,this.taskId,action,"internal",at,Date.now());
      return value;
    } catch(error) { mitigationStore.trace(this.sessionId,this.taskId,action,"internal",at,Date.now(),String(error)); throw error; }
  }

  private stage(stage: number, message: string) { mitigationStore.stage(this.sessionId,this.taskId,stage,message); }
  private context(roadId: number, intersectionId?: number) { return this.request("mitigation_context",{roadId,...(intersectionId===undefined?{}:{intersectionId})}) as Promise<MitigationContext>; }
  private snapshot(context: MitigationContext): Observation { return {simulationTime:context.simulationTime,approaches:context.approaches,currentStage:context.signal?.currentStage ?? null}; }
  private fingerprint(context: MitigationContext) { return JSON.stringify({map:context.map,scene:context.scene,seed:context.randomSeed,road:context.roadId,intersection:context.intersectionId,stages:context.signal?.stages,offset:context.signal?.offsetSeconds}); }

  private async observe(context: MitigationContext, duration: number, round: string) {
    const deadline=Date.now()+600000;
    const samples = [this.snapshot(await this.context(context.roadId,context.intersectionId))];
    const start = samples[0].simulationTime;
    const sampleKey = round === "基准验证" ? "baselineSamples" : round === "方案验证" ? "candidateSamples" : "diagnosisObservations";
    mitigationStore.update(this.sessionId,this.taskId,{round,roundDeadline:deadline,advancedSeconds:0,[sampleKey]:[...samples]});
    while (true) {
      this.controller!.signal.throwIfAborted();
      if(Date.now()>deadline)throw new Error(`${round}超过 10 分钟，正在恢复任务起点。`);
      if (mitigationStore.get(this.sessionId)?.pauseRequested) {
        mitigationStore.update(this.sessionId,this.taskId,{observationPaused:true,message:`${round} · 已暂停观察，仿真停在最近采样点；执行时限继续计时。`});
        await new Promise<void>((resolve,reject)=>{
          const signal=this.controller!.signal;
          const abort=()=>{clearTimeout(timer);reject(signal.reason);};
          const timer=setTimeout(()=>{signal.removeEventListener("abort",abort);resolve();},150);
          signal.addEventListener("abort",abort,{once:true});
        });
        continue;
      }
      mitigationStore.update(this.sessionId,this.taskId,{observationPaused:false});
      if(samples.at(-1)!.simulationTime >= start + duration - .001)break;
      await this.request("run_for",{durationSeconds:Math.min(5,start+duration-samples.at(-1)!.simulationTime),displaySpeed:this.displaySpeed});
      const current = await this.context(context.roadId,context.intersectionId);
      if (current.simulationTime <= samples.at(-1)!.simulationTime) throw new Error("仿真没有推进，验证已停止。");
      samples.push(this.snapshot(current));
      mitigationStore.update(this.sessionId,this.taskId,{round,context:current,advancedSeconds:current.simulationTime-start,observations:[...samples],[sampleKey]:[...samples],message:`${round} · 已推进 ${(current.simulationTime-start).toFixed(0)} / ${duration} 秒仿真时间 · ${this.displaySpeed}×`});
    }
    mitigationStore.update(this.sessionId,this.taskId,{roundDeadline:undefined,observationPaused:false,pauseRequested:false});
    return samples;
  }

  async execute(action: string, params: Record<string,unknown>, sessionId: string, callId: string, signal: AbortSignal, sourceDetection?: CongestionResult) {
    signal.throwIfAborted();
    if (this.running || this.cancelling) throw new Error("已有配时任务正在执行或恢复。");
    if (action === "analyze_congestion_cause") {
      if (this.locked) throw new Error("已有配时任务等待选择或决策，请先完成或取消当前任务。");
      // The browser command may arrive before the SSE tool-start notification.
      const task=mitigationStore.get(sessionId);
      if (task?.id !== callId && !mitigationStore.start(sessionId,callId,action)) throw new Error("已有其他配时任务，请先完成或取消。");
      if (mitigationStore.get(sessionId)?.status !== "running") throw new Error("本次任务已结束或取消，请重新发起分析。");
      mitigationStore.scope(sessionId, callId);
      if(sourceDetection)mitigationStore.attachSource(sessionId,callId,sourceDetection);
      this.sessionId=sessionId;this.taskId=callId;
    }
    if (action !== "analyze_congestion_cause") {
      const task = mitigationStore.get(sessionId), approval=this.approval;
      if (!task || task.id !== params.taskId || task.id !== this.taskId || sessionId !== this.sessionId || !approval || approval.token !== params.approvalToken || approval.version !== params.version) throw new Error("缺少本次用户选择授权，或方案已过期。请在方案面板重新选择。");
      if (action === "evaluate_signal_plan" && task.status !== "awaiting_selection" || action === "finalize_signal_trial" && task.status !== "awaiting_decision") throw new Error("当前任务阶段不允许此操作。");
    }
    this.running = true;
    this.controller = new AbortController();
    const abort=()=>this.controller?.abort(signal.reason);
    signal.addEventListener("abort",abort,{once:true});
    if(signal.aborted) abort();
    const timeout=setTimeout(()=>this.controller?.abort(new Error("配时任务执行超时。")),action==="analyze_congestion_cause"?600000:1250000);
    const traceAt=Date.now(); mitigationStore.trace(sessionId,this.taskId,action,"mcp",traceAt);
    try {
      if (action === "analyze_congestion_cause") {
        const state = await this.raw("get_simulation_state") as {capabilities?:string[]};
        if(!state.capabilities?.includes("traffic-pi-mitigation-v1")) throw new Error("仿真包尚未提供配时验证控制桥，请更新并重新打开仿真。");
        if(!state.capabilities.includes("traffic-pi-signal-visual-v1")) throw new Error("当前仿真包缺少真实信号可视化能力（traffic-pi-signal-visual-v1），请更新并重新加载场景。");
        let roadId=params.roadId as number|undefined;
        if(roadId===undefined) { const detected=screenCongestion(await this.raw("get_road_metrics")); roadId=detected.roads[0]?.roadId; }
        if(!Number.isInteger(roadId) || roadId! < 0) throw new Error("当前没有可自动选定的拥堵点，请先检测，或从道路卡片指定目标。");
        await this.request("mitigation_begin"); this.locked=true;
        this.heartbeat=setInterval(()=>{void this.raw("mitigation_heartbeat",{leaseId:this.taskId}).catch(()=>{void this.cancel("仿真连接丢失，任务已中止。");});},4000);
        const context=await this.context(roadId!);
        mitigationStore.update(sessionId,this.taskId,{context,originalPlan:structuredClone(context.signal),targetRoadId:roadId,panelOpen:true,planApplied:false});
        if(context.signal) await this.request("set_signal_visualization",{enabled:true,intersectionId:context.intersectionId});
        await this.show([roadId!],this.controller.signal);
        this.stage(1,"正在关联目标道路、信号相位与下游车道…");
        const related=[...new Set([roadId!,...context.approaches.map(a=>a.roadId),...(context.signal?.stages.flatMap(s=>s.movements.filter(m=>!m.crosswalk && m.fromRoadId===roadId).map(m=>m.toRoadId))??[])])];
        await this.request("highlight_roads",{roads:related.map(id=>({roadId:id,level:id===roadId?"severe":"warning"}))});
        await this.show(related,this.controller.signal);
        const cycle=context.signal?.stages.reduce((sum,s)=>sum+s.durationSeconds,0) ?? 0;
        const samples=context.signal && cycle>0 && context.signal.stages.every(s=>s.fixed)?await this.observe(context,Math.min(300,2*cycle),"溯源观察"):[this.snapshot(context)];
        const diagnosis=diagnose(context,samples);
        const candidates=[];
        const validationErrors:string[]=[];
        for(const candidate of diagnosis.candidates) {
          try {await this.request("mitigation_validate_plan",{intersectionId:context.intersectionId,stageDurationsSeconds:candidate.durations});candidates.push(candidate);} catch(error) {if(this.controller.signal.aborted)throw error;validationErrors.push(String(error));}
        }
        const alternativeTargets=[];
        if(!candidates.length) for(const road of mitigationStore.get(sessionId)?.sourceDetection?.roads ?? []) {
          if(road.roadId===roadId)continue;
          try {
            const other=await this.context(road.roadId);
            const approach=other.approaches.find(a=>a.roadId===road.roadId);
            const reason=!other.signal?"没有信号控制":other.signal.stages.some(s=>!s.fixed)?"包含自适应相位":!other.targetStages.length?"无目标保护放行相位":!approach || !Number.isFinite(approach.downstreamOccupancy)?"缺少目标方向数据":approach.downstreamOccupancy>=.85?"下游阻塞，暂不适合增加放行":"可进一步溯源；初筛通过不代表已有合法方案";
            alternativeTargets.push({roadId:road.roadId,name:road.name,eligible:reason.startsWith("可进一步"),reason});
          } catch(error) {
            this.controller.signal.throwIfAborted();
            alternativeTargets.push({roadId:road.roadId,name:road.name,eligible:false,reason:`条件读取失败：${String(error)}`});
          }
        }
        const evidence=validationErrors.length && !candidates.length?`${diagnosis.reason} 控制桥未通过候选配时校验：${validationErrors.join("；")}`:diagnosis.reason;
        await this.request("mitigation_checkpoint",{name:"validation"});
        const readyContext=await this.context(context.roadId,context.intersectionId);
        mitigationStore.update(sessionId,this.taskId,{context:readyContext,evidence,observations:samples,diagnosisObservations:samples,candidates,panelOpen:true,alternativeTargets});
        this.stage(candidates.length?2:1,candidates.length?"已暂停，等待你选择配时方案。":"没有可执行配时方案，请查看溯源证据。");
        if(candidates.length) mitigationStore.update(sessionId,this.taskId,{status:"awaiting_selection"});
        else {await this.rollback(); mitigationStore.end(sessionId,this.taskId,"completed",evidence);}
      } else if(action === "evaluate_signal_plan") {
        const task=mitigationStore.get(sessionId)!;
        const candidate=task.candidates.find(c=>c.id===this.approval!.choice);
        if(!candidate || !task.context) throw new Error("选中的配时方案已失效。");
        this.approval=null;
        const context=await this.context(task.context.roadId,task.context.intersectionId);
        if(this.fingerprint(context)!==this.fingerprint(task.context) || Math.abs(context.simulationTime-task.context.simulationTime)>.01) throw new Error("场景或原配时发生变化，请重新分析。");
        mitigationStore.update(sessionId,this.taskId,{status:"running",panelOpen:true,selectedId:candidate.id,baselineSamples:[],candidateSamples:[],planApplied:false,previewStage:undefined});
        await this.request("set_signal_visualization",{enabled:true,intersectionId:context.intersectionId});
        this.stage(3,"正在从共同起点验证原配时…");
        await this.request("mitigation_restore",{name:"validation"});
        const baselineSamples=await this.observe(context,300,"基准验证");
        await this.request("mitigation_checkpoint",{name:"baseline_end"});
        this.stage(4,"回到共同起点，开始新方案验证…");
        await this.request("mitigation_restore",{name:"validation"});
        await this.request("mitigation_validate_plan",{intersectionId:context.intersectionId,stageDurationsSeconds:candidate.durations});
        await this.request("apply_signal_plan",{intersectionId:context.intersectionId,stageDurationsSeconds:candidate.durations});
        const applied=await this.request("get_signal_plan",{intersectionId:context.intersectionId}) as SignalPlan;
        if(applied.stages.length!==candidate.durations.length || applied.stages.some((s,i)=>Math.abs(s.durationSeconds-candidate.durations[i])>.001) || applied.offsetSeconds!==task.originalPlan?.offsetSeconds) throw new Error("新配时读取核对失败，未确认方案生效，正在恢复。");
        mitigationStore.update(sessionId,this.taskId,{planApplied:true,liveSignal:applied,message:"新方案已生效 · 配时已读取核对，开始 300 秒验证。"});
        const candidateSamples=await this.observe(context,300,"方案验证");
        await this.request("mitigation_checkpoint",{name:"candidate_end"});
        if(baselineSamples.length!==candidateSamples.length || baselineSamples.some((sample,index)=>Math.abs(sample.simulationTime-candidateSamples[index].simulationTime)>.001)) throw new Error("两轮起点或采样时刻不一致，不能作公平比较，正在恢复。");
        const baseline=summarizeObservations(baselineSamples),treatment=summarizeObservations(candidateSamples);
        const before=baseline.find(a=>a.roadId===context.roadId)!,after=treatment.find(a=>a.roadId===context.roadId)!;
        const message=after.waitingVehicleSeconds<before.waitingVehicleSeconds?"本轮目标方向等待减少；请同时检查其他方向影响。":"本轮未观察到目标方向等待减少，建议恢复原配时。";
        this.stage(5,message);
        mitigationStore.update(sessionId,this.taskId,{status:"awaiting_decision",panelOpen:true,comparison:{baseline,candidate:treatment,baselineSamples,candidateSamples,startTime:context.simulationTime,duration:300,selected:candidate,message}});
      } else if(action === "finalize_signal_trial") {
        const choice=this.approval!.choice;this.approval=null;
        await this.request("mitigation_finish",{name:choice==="keep"?"candidate_end":"baseline_end"});
        this.locked=false;this.stopHeartbeat();
        mitigationStore.update(sessionId,this.taskId,{planApplied:choice==="keep"});
        mitigationStore.end(sessionId,this.taskId,"completed",choice==="keep"?"已保留新配时与候选轮结束状态，并恢复原时间控制。":"已恢复原配时与基准轮结束状态，并恢复原时间控制。");
      } else throw new Error("未知配时任务操作。");
      const task=mitigationStore.get(sessionId)!;
      mitigationStore.trace(sessionId,this.taskId,action,"mcp",traceAt,Date.now());
      return {type:"traffic-pi-mitigation",taskId:this.taskId,status:task.status,roadId:task.targetRoadId,context:task.context,evidence:task.evidence,candidates:task.candidates,comparison:task.comparison,message:task.message,simulationTime:(await this.raw("get_simulation_state") as {simulationTime:number}).simulationTime};
    } catch(error) {
      this.controller?.abort();
      if(this.cancelling) {await this.cancelling;throw error;}
      try {await this.rollback();mitigationStore.end(sessionId,this.taskId,signal.aborted?"cancelled":"failed",String(error));}
      catch(restoreError) {mitigationStore.end(sessionId,this.taskId,"failed",`${String(error)}；恢复失败：${String(restoreError)}，请手动核查仿真。`);}
      throw error;
    } finally {clearTimeout(timeout);signal.removeEventListener("abort",abort);this.running=false;}
  }
  private stopHeartbeat() {if(this.heartbeat)clearInterval(this.heartbeat);this.heartbeat=null;}
  private async rollback() {
    try {
      if(this.locked) {await this.raw("mitigation_cancel",{leaseId:this.taskId});this.locked=false;}
    } finally {this.stopHeartbeat();this.approval=null;}
  }
  async cancel(message="任务已取消，已恢复本轮开始状态。") {
    if(this.cancelling)return this.cancelling;
    this.controller?.abort(new Error(message));
    this.cancelling=(async()=>{try {await this.rollback();mitigationStore.restored(this.sessionId,this.taskId);mitigationStore.end(this.sessionId,this.taskId,"cancelled",message);}catch(error){mitigationStore.end(this.sessionId,this.taskId,"failed",`恢复失败：${String(error)}，请手动核查仿真。`);}})();
    try {await this.cancelling;} finally {this.cancelling=null;}
  }
}
