"use client";

import type { TrafficResult } from "@/lib/traffic-results";
import type { GeoScene } from "@/lib/geo-types";

function ResultData({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>未提供</span>;
  if (Array.isArray(value)) return <div className="traffic-result-data">{value.length ? value.map((item, index) => <ResultData key={index} value={item} />) : "未提供"}</div>;
  if (typeof value === "object") return <table><tbody>{Object.entries(value).map(([key, item]) => <tr key={key}><th scope="row">{key}</th><td><ResultData value={item} /></td></tr>)}</tbody></table>;
  return <span>{String(value)}</span>;
}

export function TrafficResultsPanel({ results, expandedId, onSelect, onClose }: {
  results: TrafficResult[]; expandedId: string | null; onSelect: (result: TrafficResult) => void; onClose: () => void;
}) {
  return <aside className="traffic-results" aria-label="分析结果">
    <header><div><strong>分析结果</strong><small>{results.length} 项 · 当前页面临时保存</small></div><button type="button" onClick={onClose} aria-label="收起分析结果">收起</button></header>
    <div className="traffic-results-list">
      {!results.length && <div className="traffic-results-empty"><span aria-hidden="true">▤</span><strong>暂无分析结果</strong><p>Agent 返回地图图层、交通指标或方案对比后，会显示在这里。</p><small>切换会话分别保留，刷新后清空。</small></div>}
      {results.map(result => <article key={result.id} className="traffic-result-card" data-selected={expandedId === result.id}>
        <button type="button" onClick={() => onSelect(result)} aria-expanded={expandedId === result.id}>
          <strong>{result.title}</strong>{result.unread && <span className="traffic-result-badge">新结果</span>}
          <small>{new Date(result.receivedAt).toLocaleTimeString()} · {result.type === "publish_geo_scene" ? "GIS" : "本地仿真"}</small>
        </button>
        <code>来源：{result.toolName}</code>
        {expandedId === result.id && <div className="traffic-result-detail">
          {result.type === "publish_geo_scene" ? <><p>revision {(result.data as GeoScene).revision} · {(result.data as GeoScene).sources.reduce((sum, source) => sum + source.data.features.length, 0)} 个要素</p><p>{(result.data as GeoScene).layers.map(layer => layer.title ?? layer.id).join("、") || "暂无图层"}</p></> : <><p>仿真时间：{result.simulationTime == null ? "未提供" : String(result.simulationTime)}</p><ResultData value={result.data} /><small>字段与单位沿用工具返回值；未返回的值显示为“未提供”。</small></>}
        </div>}
      </article>)}
    </div>
  </aside>;
}
