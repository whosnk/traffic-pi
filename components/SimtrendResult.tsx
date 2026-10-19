"use client";

import { useState } from "react";
import { MarkdownBody } from "./MarkdownBody";
import type { SimtrendResult as Result } from "@/lib/simtrend-types";
import { comparisonMetrics } from "@/lib/simtrend-metrics";
import { resultArtifacts, replayTitle } from "@/lib/simtrend-artifacts";

export function SimtrendResult({ result }: { result: Result }) {
  const [showReplay, setShowReplay] = useState(false);
  const artifacts = resultArtifacts(result);
  const replays = artifacts.filter(item => item.kind === "replay");
  const metrics = result.ok ? comparisonMetrics(result.data) : [];
  const demand = result.tool === "run_demand_impact_evaluation";
  return <div className="simtrend-result">
    <p role="status"><strong>{result.status === "clarification_required" ? "需要补充信息" : result.ok ? "已完成" : "执行未完成"}</strong>{result.scenario_id && <span> · {result.scenario_id}</span>}</p>
    {result.message && <MarkdownBody>{result.message}</MarkdownBody>}
    {metrics.length > 0 && <section className="simtrend-metrics">
      <h3>指标对比</h3>
      {typeof result.data?.target_label === "string" && <p>重点对象：{result.data.target_label}</p>}
      <p>灰色：{demand ? "原始需求" : "基线方案"}；青色：{demand ? "调整需求" : "优化方案"}。变化 = 后者 − 前者，不代表所有指标越小越好。</p>
      <table><thead><tr><th>指标</th><th>前</th><th>后</th><th>变化</th></tr></thead>
        <tbody>{metrics.map(row => <tr key={row.key}>
          <th scope="row">{row.label}（{row.unit}）<div className="simtrend-bars" aria-hidden="true"><i style={{ width: `${100 * row.before / row.max}%` }} /><i style={{ width: `${100 * row.after / row.max}%` }} /></div></th>
          <td>{row.before.toFixed(row.unit === "辆" ? 0 : 2)}</td><td>{row.after.toFixed(row.unit === "辆" ? 0 : 2)}</td><td>{row.delta > 0 ? "+" : ""}{row.delta.toFixed(row.unit === "辆" ? 0 : 2)}</td>
        </tr>)}</tbody>
      </table><small>到达车辆不含仿真结束时仍在途的车辆；缺失指标不补零。各行条形独立缩放。</small>
    </section>}
    {replays.length > 0 && <>
      <button type="button" onClick={() => setShowReplay(value => !value)}>{showReplay ? "收起回放" : "播放仿真回放"}</button>
      {showReplay && <div className="simtrend-replays">{replays.map(item => <figure key={item.id}>
        <figcaption>{replayTitle(item)}</figcaption>
        {/* Run-specific GIFs must be served directly, without Next image optimization. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={item.url} alt={item.name} loading="lazy" />
      </figure>)}</div>}
    </>}
    {artifacts.length > 0 && <details><summary>下载运行文件（{artifacts.length}）</summary><div className="simtrend-downloads">{artifacts.map(item => <a key={item.id} href={item.url} download={item.name}>{item.label}</a>)}</div></details>}
    <details><summary>结构化结果与指标</summary><pre>{JSON.stringify(result.data ?? result, null, 2)}</pre></details>
  </div>;
}
