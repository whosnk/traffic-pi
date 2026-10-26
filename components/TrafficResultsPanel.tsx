"use client";
import { useEffect, useState } from "react";
import { abstreetRuntime, useAbstreetRuntime } from "@/lib/abstreet-runtime";
import { abstreetScenarios } from "@/lib/traffic-scenarios";
import { startMitigation, mitigationStore, useMitigationTask } from "@/lib/mitigation-store";

import type { TrafficResult } from "@/lib/traffic-results";
import type { GeoScene } from "@/lib/geo-types";
import { SimtrendResult } from "./SimtrendResult";
import type { SimtrendResult as SimtrendResultData } from "@/lib/simtrend-types";
import type { IncidentDraftResult } from "@/lib/simtrend-draft";
import type { CongestedRoad } from "@/lib/congestion";
import type { CongestionResult } from "@/lib/congestion-executor";
import type { TrialComparison } from "@/lib/mitigation";

function ResultData({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>未提供</span>;
  if (Array.isArray(value)) return <div className="traffic-result-data">{value.length ? value.map((item, index) => <ResultData key={index} value={item} />) : "未提供"}</div>;
  if (typeof value === "object") return <table><tbody>{Object.entries(value).map(([key, item]) => <tr key={key}><th scope="row">{key}</th><td><ResultData value={item} /></td></tr>)}</tbody></table>;
  return <span>{String(value)}</span>;
}

function MitigationResult({result,sessionId}:{result:TrafficResult;sessionId?:string}) {
  const data=result.data as Record<string,unknown>;
  const comparison=data.comparison as TrialComparison|undefined;
  return <div className="traffic-result-detail"><p>{String(data.message)}</p><p>目标道路 {String(data.roadId??"未提供")} · 仿真时刻 {String(data.simulationTime??"未提供")} 秒</p><p>{String(data.evidence??"未提供")}</p>
    {data.preset === true && <small>{String(data.sourceNote)}</small>}
    {comparison && <><p>同一起点 · 每轮 {comparison.duration} 秒 · 原配时 → 新配时</p>{comparison.baseline.map(before=>{
      const after=comparison.candidate.find(a=>a.roadId===before.roadId);
      return <p key={before.roadId}>道路 {before.roadId}<br/>平均排队：{before.meanQueue.toFixed(1)} → {after?.meanQueue.toFixed(1)??"未提供"} 辆<br/>等待：{before.waitingVehicleSeconds.toFixed(0)} → {after?.waitingVehicleSeconds.toFixed(0)??"未提供"} 车辆秒<br/>通过：{before.passedVehicles} → {after?.passedVehicles??"未提供"} 辆</p>;
    })}<small>等待车辆秒由 5 秒间隔排队采样积分估计，范围限于该路口。</small></>}
    {sessionId && mitigationStore.get(sessionId)?.id===data.taskId && <button type="button" onClick={()=>mitigationStore.panel(sessionId,true)}>查看任务与方案</button>}
  </div>;
}

export function TrafficResultsPanel({ results, expandedId, onSelect, onClose, onFocusRoad, sessionId }: {
  sessionId?: string;
  results: TrafficResult[]; expandedId: string | null; onSelect: (result: TrafficResult) => void; onClose: () => void;
  onFocusRoad?: (roadId: number, result: CongestionResult) => void;
}) {
  const [error, setError] = useState("");
  useAbstreetRuntime();
  const task=useMitigationTask(sessionId ?? null);
  const [tab,setTab]=useState<"current"|"history">("history");
  const current=!!task && !task.preset && abstreetRuntime.matches(task);
  useEffect(()=>{if(task?.panelOpen && !task.preset)setTab("current");},[task?.id,task?.panelOpen,task?.preset]);
  const start = (roadId: number, result: CongestionResult, preset = false) => {
    if (!startMitigation(sessionId ?? null, roadId, undefined, result, preset)) setError(abstreetRuntime.actionReason("analyze_congestion_cause", result) || (mitigationStore.switchBlocked() ? "已有任务或恢复未确认，请先返回当前任务完成或取消。" : "Agent 正忙或尚未准备好，请等待后重试。"));
    else setError("");
  };
  return <aside className="traffic-results" aria-label="分析结果">
    <header><div><strong>分析结果</strong><small>{results.length} 项 · 当前页面临时保存</small></div><button type="button" onClick={onClose} aria-label="收起分析结果">收起</button></header>
    <div className="traffic-result-tabs" role="group" aria-label="信控与历史结果"><button type="button" aria-pressed={tab==="current"} onClick={()=>{setTab("current");if(sessionId)mitigationStore.panel(sessionId,true);}}>当前治理</button><button type="button" aria-pressed={tab==="history"} onClick={()=>{setTab("history");if(sessionId)mitigationStore.panel(sessionId,false);}}>历史结果 · {results.length}</button></div>
    <div id="traffic-mitigation-host" className="traffic-mitigation-host" hidden={tab!=="current" || !current || !task?.panelOpen}/>
    {tab==="current" && (!current || !task?.panelOpen) && <div className="traffic-results-empty"><strong>{current?"治理面板已收起":"暂无当前治理任务"}</strong><p>从拥堵道路开始真实溯源，信号、配时和两轮验证将在这里展示。</p>{current && <button type="button" onClick={()=>sessionId&&mitigationStore.panel(sessionId,true)}>打开当前治理</button>}</div>}
    {error && <p role="alert">{error}</p>}
    <div className="traffic-results-list" hidden={tab!=="history"}>
      {!results.length && <div className="traffic-results-empty"><span aria-hidden="true">▤</span><strong>暂无分析结果</strong><p>Agent 返回地图图层、交通指标或方案对比后，会显示在这里。</p><small>切换会话分别保留，刷新后清空。</small></div>}
      {results.map(result => <article key={result.id} className="traffic-result-card" data-selected={expandedId === result.id}>
        <button type="button" onClick={() => onSelect(result)} aria-expanded={expandedId === result.id}>
          <strong>{result.title}</strong>{result.unread && <span className="traffic-result-badge">新结果</span>}
          <small>{new Date(result.receivedAt).toLocaleTimeString()} · {(result.data as Record<string,unknown>).preset === true ? "预设参数推演 · 非真实验证" : result.type === "publish_geo_scene" ? "GIS 空间分析" : result.type === "simtrend_draft" ? "SUMO 任务草案" : result.type === "simtrend" ? "SUMO 实验结果" : `A/B Street · ${abstreetScenarios.find(item => item.id === result.scenarioId)?.name ?? "历史场景"} · 批次 ${result.runId?.slice(0,8) ?? "未记录"}`}</small>
        </button>
        <code>来源：{result.toolName}</code>
        {expandedId === result.id && result.type === "simtrend" && <SimtrendResult result={result.data as SimtrendResultData} />}
        {expandedId === result.id && result.type === "simtrend_draft" && <div className="traffic-result-detail"><p>{(result.data as IncidentDraftResult).message}</p><p>草案生成时未运行仿真。当前参数与修改请查看中间“创建仿真任务”面板。</p></div>}
        {expandedId===result.id && ["analyze_congestion_cause","evaluate_signal_plan","finalize_signal_trial"].includes(result.type) && <MitigationResult result={result} sessionId={sessionId}/>}
        {expandedId === result.id && result.type === "detect_congestion" && <div className="traffic-result-detail">
          <p>{String((result.data as Record<string, unknown>).message)}</p><p>场景：{String(((result.data as Record<string, unknown>).state as Record<string, unknown>)?.scene ?? "未提供")}<br />采集时间：{String((result.data as Record<string, unknown>).metricsCollectedAt ?? "未提供")}<br />仿真时间：{String(result.simulationTime ?? "未提供")}</p>
          {((result.data as Record<string, unknown>).roads as CongestedRoad[]).map((road, index) => <div key={road.roadId} className="traffic-congestion-road">
            <button type="button" disabled={!abstreetRuntime.matches(result)} onClick={() => onFocusRoad?.(road.roadId, result.data as CongestionResult)}>{index + 1}. {road.name && road.name !== "???" ? road.name : `道路 ${road.roadId}`} · 定位</button>
            <button type="button" disabled={!sessionId || mitigationStore.switchBlocked() || !abstreetRuntime.matches(result)} onClick={()=>start(road.roadId,result.data as CongestionResult)}>分析缓解方案</button>
            {!abstreetRuntime.matches(result) && <small>历史批次 · 仅供查阅，请在当前场景重新检测。</small>}
            {mitigationStore.switchBlocked() && <small>当前任务未结束或恢复未确认，请先处理当前任务。</small>}
            <details><summary>其他方式</summary><small>预设参数模型 · 不修改真实配时</small><button type="button" disabled={!sessionId || mitigationStore.switchBlocked() || !abstreetRuntime.matches(result)} onClick={()=>start(road.roadId,result.data as CongestionResult,true)}>预设模型推演</button></details>
            <p>道路 ID {road.roadId} · 排队 {road.queueVehicles} 辆 · 历史平均车速 {road.meanVehicleSpeedKph.toFixed(1)} km/h<br />平均累计延误：{Number.isFinite(road.meanVehicleDelaySeconds) ? `${road.meanVehicleDelaySeconds!.toFixed(1)} 秒` : "未提供"}</p>
          </div>)}
          <small>{String((result.data as Record<string, unknown>).rule)} {String((result.data as Record<string, unknown>).samplingNote)}</small>
        </div>}
        {expandedId === result.id && !["analyze_congestion_cause","evaluate_signal_plan","finalize_signal_trial"].includes(result.type) && result.type !== "simtrend" && result.type !== "simtrend_draft" && result.type !== "detect_congestion" && <div className="traffic-result-detail">
          {result.type === "publish_geo_scene" ? <><p>revision {(result.data as GeoScene).revision} · {(result.data as GeoScene).sources.reduce((sum, source) => sum + source.data.features.length, 0)} 个要素</p><p>{(result.data as GeoScene).layers.map(layer => layer.title ?? layer.id).join("、") || "暂无图层"}</p></> : <><p>仿真时间：{result.simulationTime == null ? "未提供" : String(result.simulationTime)}</p><ResultData value={result.data} /><small>字段与单位沿用工具返回值；未返回的值显示为“未提供”。</small></>}
        </div>}
      </article>)}
    </div>
  </aside>;
}
