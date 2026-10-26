"use client";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { MitigationTask } from "@/lib/mitigation-store";
import { SignalControlDetails } from "./SignalControlDetails";
import styles from "./AbstreetPanel.module.css";

export function MitigationPanel({task,targets,onTarget,onClose,onChoose,onCancel,onPreview,onFocus,onPause,agentBusy=false}:{task:MitigationTask;targets?:{roadId:number;name?:string}[];onTarget:(roadId:number)=>Promise<void>;onClose:()=>void;onChoose:(choice:string)=>Promise<void>;onCancel:()=>void;onPreview:(stage?:number)=>void;onFocus:(roadId:number)=>void;onPause:()=>void;agentBusy?:boolean}) {
  const box=useRef<HTMLElement>(null);
  const [host,setHost]=useState<HTMLElement|null>(null);
  useEffect(()=>{setHost(document.getElementById("traffic-mitigation-host"));},[]);
  const [busy,setBusy]=useState(false), [error,setError]=useState("");
  const [submitted,setSubmitted]=useState("");
  const pending=submitted===`${task.id}:${task.status}`;
  useEffect(()=>{
    if(!task.panelOpen)return;
    const previous=document.activeElement as HTMLElement|null;
    box.current?.focus();
    return()=>{if(previous?.isConnected)previous.focus();};
  },[task.panelOpen,host]);
  if(!task.panelOpen || (!task.preset && !host))return null;
  const observations=task.diagnosisObservations??task.observations;
  const choose=async(choice:string)=>{setBusy(true);setError("");try{await onChoose(choice);if(!task.preset)setSubmitted(`${task.id}:${task.status}`);}catch(error){setError(String(error));}finally{setBusy(false);}};
  return createPortal(<div className={task.preset?styles.modalBackdrop:styles.dockBackdrop}>
    <section className={`${styles.mitigationDialog} ${task.preset?"":styles.mitigationDock}`} ref={box} role={task.preset?"dialog":"region"} aria-modal={task.preset?true:undefined} aria-label="拥堵缓解方案" tabIndex={-1} onKeyDown={event=>{
      if(event.key==="Escape"){event.stopPropagation();onClose();}
      if(task.preset && event.key==="Tab"){
        const elements=Array.from(box.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],select')??[]);
        const first=elements[0],last=elements.at(-1);
        if(event.shiftKey && (document.activeElement===first || document.activeElement===box.current)){event.preventDefault();last?.focus();}
        else if(!event.shiftKey && (document.activeElement===last || document.activeElement===box.current)){event.preventDefault();first?.focus();}
      }
    }}>
      <header><div><small>{task.preset ? "预设参数推演 · 非真实验证" : "真实 A/B Street 验证 · 本地合成交通"}</small><h2>{task.status==="awaiting_decision"?task.preset?"查看预设推演，再决定方案":"查看真实效果，再决定配时":task.status==="awaiting_selection"?"为当前拥堵点选择方案":"拥堵溯源与验证结果"}</h2></div><button type="button" aria-label="收起方案面板" onClick={onClose}>×</button></header>
      <div className={styles.mitigationBody}>
      <p>目标：{task.context?.roadName && task.context.roadName!=="???"?task.context.roadName:`道路 ${task.targetRoadId??"未指定"}`}（道路 ID {task.targetRoadId??"未提供"}） · 路口 {task.context?.intersectionId??"未提供"}</p>
      <p>重庆渝中半岛 · 引擎 A/B Street · {task.preset?"预设模型时刻":"仿真时刻"} {task.context?.simulationTime?.toFixed(0)??"未提供"} 秒 · 场景 {task.context?.scene??"未提供"} · 种子 {task.context?.randomSeed??"未提供"}</p>
      {task.sourceDetection && <small>承接拥堵检测 · 采集于 {new Date(task.sourceDetection.metricsCollectedAt).toLocaleTimeString()} · 初始排队 {task.sourceDetection.roads.find(road=>road.roadId===task.targetRoadId)?.queueVehicles??"未提供"} 辆</small>}
      {["awaiting_selection","completed"].includes(task.status) && !!targets?.length && <label>改选拥堵道路（将作废当前方案）<select aria-label="改选拥堵道路" disabled={busy || pending || agentBusy} value={task.targetRoadId} onChange={async event=>{setBusy(true);setError("");try{await onTarget(Number(event.target.value));}catch(error){setError(String(error));}finally{setBusy(false);}}}>{targets.map(road=><option key={road.roadId} value={road.roadId}>{road.name && road.name!=="???"?road.name:`道路 ${road.roadId}`}</option>)}</select></label>}
      <details open={task.stage<3 || task.preset} className={styles.diagnosis}><summary>溯源证据与观察范围</summary><strong>{task.status==="failed"?"任务未完成":"可能原因与证据"}</strong><p>{task.evidence || task.message}</p>{task.context && <><p>{task.preset?"模型观察":"溯源观察"} {Math.max(0,(observations.at(-1)?.simulationTime??0)-(observations[0]?.simulationTime??0)).toFixed(0)} 秒 · {task.preset?"预设需求与信号放行关系":"道路等待与信号状态来自控制桥"}</p><p>目标方向{task.preset?"模型":"采样"}排队 {observations.length?Math.min(...observations.map(s=>s.approaches.find(a=>a.roadId===task.targetRoadId)?.queueVehicles??0)):0}–{observations.length?Math.max(...observations.map(s=>s.approaches.find(a=>a.roadId===task.targetRoadId)?.queueVehicles??0)):0} 辆。尚不能排除需求波动、转向冲突等其他影响。</p></>}</details>
      {!task.preset && <SignalControlDetails task={task} onPreview={onPreview} onFocus={onFocus}/>}
      {!!task.alternativeTargets?.length && <section aria-label="其他拥堵道路条件初筛"><h3>其他目标 · 只读初筛</h3>{task.alternativeTargets.map(target=><div key={target.roadId}><p>道路 {target.roadId} · {target.reason}</p><button type="button" disabled={busy || !target.eligible} onClick={()=>void onTarget(target.roadId).catch(error=>setError(String(error)))}>重新溯源此道路</button></div>)}</section>}
      {task.preset && <small>基于预设信控、需求及放行参数推演；未修改 A/B Street 的实际配时，地图车辆以其实际运行为准。</small>}
      {error && <p role="alert">{error}</p>}
      {task.status==="awaiting_selection" && <><p>{task.preset?"选择方案后，分别推演 5 分钟原配时和新配时，压缩时间展示排队变化。":"仿真已暂停。选择方案即授权本地仿真写操作；随后从同一检查点，以 5× 速度各验证 300 秒，每 5 秒采样。比较后仍需你决定保留或恢复。"}</p><div className={styles.candidateGrid}>{task.candidates.map(candidate=><article key={candidate.id}>
        <h3>{candidate.title}</h3><p>{candidate.reason}</p>
        {task.preset && <table><thead><tr><th>相位与服务道路</th><th>原时长</th><th>新时长</th></tr></thead><tbody>{(task.originalPlan??task.context?.signal)?.stages.map((stage,index)=><tr key={index}><td>相位 {index+1} · {[...new Set(stage.movements.filter(m=>!m.crosswalk).map(m=>`${m.fromRoadId} → ${m.toRoadId}`))].join("、") || "行人通行"}</td><td>{stage.durationSeconds}s</td><td>{candidate.durations[index]}s</td></tr>)}</tbody></table>}
        <small>{candidate.impact}</small>{task.preset && <button type="button" disabled={busy || pending || agentBusy} onClick={()=>void choose(candidate.id)}>选择「{candidate.title}」并验证</button>}
      </article>)}</div></>}
      {task.comparison && <><p>{task.comparison.message}</p><p>同一起点 {task.comparison.startTime.toFixed(0)} 秒 · 两轮各 {task.comparison.duration} 秒 · 下表为原配时 → 新配时</p><div className={styles.comparisonTable}><table><thead><tr><th>进口道路</th><th>平均排队（辆）</th><th>最大排队（辆）</th><th>等待（车辆秒）</th><th>通过（辆）</th><th>结束排队（辆）</th></tr></thead><tbody>{task.comparison.baseline.map(before=>{const after=task.comparison!.candidate.find(a=>a.roadId===before.roadId)!;return <tr key={before.roadId} data-target={before.roadId===task.targetRoadId}><td>{before.name==="???"?`道路 ${before.roadId}`:before.name}（{before.roadId}）</td>{(["meanQueue","maxQueue","waitingVehicleSeconds","passedVehicles","endQueue"] as const).map(key=><td key={key}>{before[key].toFixed(1)} → {after[key].toFixed(1)}</td>)}</tr>;})}</tbody></table></div><p role="status">{task.comparison.candidate.some(after=>after.roadId!==task.targetRoadId && after.waitingVehicleSeconds>(task.comparison!.baseline.find(before=>before.roadId===after.roadId)?.waitingVehicleSeconds??0)) ? "注意：本轮其他方向存在等待增加，请逐行检查后再决定。" : "其他方向未观察到等待增加；样本仅限本路口本轮观察。"}</p><small>等待车辆秒数由每 5 秒排队采样作梯形积分估计。只代表该路口本轮观察，不能推断全路网或普遍效果。</small></>}
      </div>
      <footer>{!task.preset && task.status==="awaiting_selection" && task.candidates.map(candidate=><button key={candidate.id} type="button" disabled={busy || pending || agentBusy} onClick={()=>void choose(candidate.id)}>选择「{candidate.title}」并验证</button>)}{!task.preset && task.status==="running" && task.roundDeadline && <button type="button" onClick={onPause}>{task.pauseRequested?"继续验证":"暂停观察"}</button>}{task.status==="awaiting_decision"?<><button type="button" disabled={busy || pending || agentBusy} onClick={()=>void choose("keep")}>{task.preset?"保留推演方案":"保留新配时"}</button><button type="button" disabled={busy || pending || agentBusy} onClick={()=>void choose("restore")}>{task.preset?"恢复推演原方案":"恢复原配时"}</button></>:["running","awaiting_selection"].includes(task.status)?<button type="button" disabled={busy} onClick={onCancel}>取消任务并恢复</button>:null}<span role="status">{pending?"选择已提交，等待 Agent 调用授权工具…":busy?task.preset?"正在执行所选方案…":"正在提交选择，请等待 Agent 执行…":task.message}</span></footer>
    </section>
  </div>,task.preset?document.body:host!);
}
