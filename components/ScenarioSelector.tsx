"use client";

import { useEffect, useState } from "react";
import { simtrendRequest, type SimtrendScenario } from "@/lib/simtrend-types";
import { trafficScenarios, type TrafficScenario } from "@/lib/traffic-scenarios";

export function ScenarioSelector({ active, currentId, blockedReason, onSelect }: {
  active: boolean; currentId: string; blockedReason: string; onSelect: (scenario: TrafficScenario) => void;
}) {
  const [scenarios, setScenarios] = useState<SimtrendScenario[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController();
    setLoading(true);
    simtrendRequest<{ scenarios: SimtrendScenario[] }>({ action: "scenarios" }, abort.signal)
      .then(data => { if (!abort.signal.aborted) { setScenarios(data.scenarios); setError(""); } })
      .catch(error => { if (!abort.signal.aborted) { setScenarios([]); setError(error.message); } })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [active, reload]);
  return <section className="traffic-scenarios" aria-label="场景管理">
    <h2>选择交通场景</h2>
    <p>A/B Street 是主可视化；SimTrend 提供 SUMO 实验任务。两套引擎尚未实时同步，道路 ID 不通用。GIS 用于分析与图层。</p>
    <p>切换只打开对应界面，不启动 SUMO。已提交 jobs 在后台继续；返回原场景可查看运行记录。草稿与结果保留原场景归属，空间定位在切换时清空。</p>
    {blockedReason && <p role="status">{blockedReason}</p>}
    {loading && <p role="status">正在读取实验场景…</p>}
    {error && <p role="alert">SUMO 场景当前不可用：{error}。请检查项目信任、Python 及 SimTrend 连接后重试。</p>}
    <button type="button" disabled={loading} onClick={() => setReload(value => value + 1)}>刷新场景列表</button>
    {(["urban", "highway"] as const).map(category => <section key={category}>
      <h3>{category === "urban" ? "城市道路" : "高速公路"}</h3>
      <div className="traffic-scenario-grid">{trafficScenarios(scenarios).filter(item => item.category === category).map(item => <article key={item.id} data-current={currentId === item.id}>
        <h4>{item.name}{currentId === item.id ? " · 当前" : ""}</h4><p>{item.description}</p>
        <dl><div><dt>计算引擎</dt><dd>{item.engine === "abstreet" ? "A/B Street" : "SUMO"}</dd></div><div><dt>可视化</dt><dd>{item.visualization === "abstreet" ? "A/B Street 主地图" : item.visualization === "sumo-native" ? "空间对象与实验结果回放" : "待开发"}</dd></div><div><dt>状态</dt><dd>{item.availabilityNote}</dd></div></dl>
        <small>{item.source}</small><p>{item.capabilities.join(" · ") || "暂无可运行能力"}</p>
        <button type="button" disabled={item.availability !== "implemented" || !item.entryTarget || !!blockedReason} onClick={() => onSelect(item)}>{item.entryTarget === "abstreet" ? "进入主工作台" : item.entryTarget === "sumo" ? "打开实验场景" : "规划中 · 不可运行"}</button>
      </article>)}</div>
    </section>)}
  </section>;
}
