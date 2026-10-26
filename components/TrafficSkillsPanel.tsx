"use client";

import { useEffect, useRef, useState } from "react";
import { startCongestionAnalysis } from "@/lib/traffic-workflow";
import { abstreetRuntime, useAbstreetRuntime } from "@/lib/abstreet-runtime";
import { useCongestionTask } from "@/lib/congestion-store";
import { mitigationStore, startMitigation, useMitigationTask } from "@/lib/mitigation-store";

const skills = [
  { name: "traffic-mitigation", title: "拥堵溯源与缓解", description: "承接发现的拥堵，由你选择缓解方案，比较效果后决定保留或恢复。", steps: ["继承目标道路及拥堵检测指标", "展示证据并等待用户选择方案", "同起点比较后决定保留或恢复"], tools: ["analyze_congestion_cause", "evaluate_signal_plan", "finalize_signal_trial"], output: "溯源证据、可选择配时方案、同起点效果对比及保留／恢复操作。" },
  { name: "traffic-congestion", title: "拥堵分析", description: "检测当前疑似拥堵道路，在仿真地图高亮并定位。", steps: ["准备当前场景并读取道路指标", "按排队与车速识别疑似拥堵", "高亮、聚焦道路并解释检测结果"], tools: ["detect_congestion"], output: "带采集时间的道路排名、拥堵高亮和道路详情；完整执行过程显示在仿真顶部。" },
  { name: "traffic-simulation", title: "仿真控制", description: "检查场景、推进仿真，读取运行状态与拥堵指标。", steps: ["确认已连接工具、路网和需求", "核对仿真时长与时间步长", "推进仿真并读取真实结果"], tools: ["get_simulation_state", "run_until", "get_road_metrics"], output: "场景与仿真时间、道路速度和延误；缺失指标明确标注。" },
  { name: "traffic-signal-analysis", title: "信号配时分析", description: "依据路口流量、排队与相位数据诊断配时问题。", steps: ["读取路口、周期、相位和时间窗", "分析拥堵与配时约束", "获得授权后修改，并保留恢复方案"], tools: ["get_intersection_metrics", "get_signal_plan", "apply_signal_plan", "restore_signal_plan"], output: "路口诊断与配时建议，注明统计口径和数据来源。" },
  { name: "traffic-scenario-comparison", title: "方案对比评估", description: "检查可比条件，评估基准与候选方案的交通差异。", steps: ["核对路网、需求、统计时段与随机种子", "采集基准和候选方案真实指标", "比较绝对差与相对变化，说明证据范围"], tools: ["capture_metrics", "compare_metrics", "publish_geo_scene"], output: "延误、速度、排队及吞吐量差异；可通过 GIS 展示道路结果。" },
];

export function TrafficSkillsPanel({ onClose, sessionId }: { onClose: () => void; sessionId: string | null }) {
  const close = useRef<HTMLButtonElement>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const task = useCongestionTask(sessionId);
  useMitigationTask(sessionId);
  useAbstreetRuntime();
  const capabilityReason = abstreetRuntime.actionReason("detect_congestion") || (mitigationStore.recoveryRequired() ? "恢复未确认，请先处理仿真任务。" : "");
  const [error, setError] = useState("");
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); } };
    document.addEventListener("keydown", onKey, true);
    return () => { document.removeEventListener("keydown", onKey, true); previous?.focus(); };
  }, [onClose]);
  return <aside className="traffic-skills-panel" aria-label="专属交通技能">
    <header><div><small>TRAFFIC SKILLS</small><strong>专属交通技能</strong></div><button ref={close} type="button" onClick={onClose} aria-label="关闭交通技能">关闭</button></header>
    <p>了解交通技能与工具的联动。展开卡片查看说明，点击“开始分析”执行拥堵分析。</p>
    {error && <p role="alert">{error}</p>}
    {capabilityReason && <p role="status">{capabilityReason}</p>}
    {skills.map((skill, index) => <article key={skill.name} className="traffic-skill-card" data-expanded={expanded === skill.name}>
      <button type="button" aria-expanded={expanded === skill.name} aria-controls={`skill-${skill.name}`} onClick={() => setExpanded(current => current === skill.name ? null : skill.name)}>
        <span className="traffic-skill-card-head">0{index + 1} · 专属技能</span><strong>{skill.title}</strong><code>{skill.name}</code><p>{skill.description}</p>
      </button>
      {skill.name === "traffic-congestion" && <button className="traffic-skill-start" type="button" disabled={!!capabilityReason || task?.status === "running" || mitigationStore.switchBlocked()} onClick={() => {
        if (startCongestionAnalysis(sessionId)) onClose();
        else setError("当前 Agent 正忙或尚未准备好，请等待或停止当前任务后重试。");
      }}>{task?.status === "running" ? "分析执行中" : "开始分析"}</button>}
      {skill.name === "traffic-mitigation" && <button className="traffic-skill-start" type="button" disabled={!!capabilityReason || task?.status==="running" || mitigationStore.switchBlocked()} onClick={()=>{if(startMitigation(sessionId))onClose();else setError("Agent 正忙或已有任务，请等待或取消后重试。");}}>分析缓解方案</button>}
      <div id={`skill-${skill.name}`} className="traffic-skill-description"><strong>处理步骤</strong><ol>{skill.steps.map(step => <li key={step}>{step}</li>)}</ol><strong>关联工具</strong><div className="traffic-skill-tools">{skill.tools.map(tool => <span key={tool}>{tool}</span>)}</div><strong>预期产出</strong><p>{skill.output}</p><small>实际使用需要加载技能并连接相应 MCP 工具。</small></div>
    </article>)}
  </aside>;
}
