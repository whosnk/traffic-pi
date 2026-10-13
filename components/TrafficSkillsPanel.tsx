"use client";

import { useEffect, useRef, useState } from "react";

const skills = [
  { name: "traffic-simulation", title: "仿真控制", description: "检查场景、推进仿真，读取运行状态与拥堵指标。", steps: ["确认已连接工具、路网和需求", "核对仿真时长与时间步长", "推进仿真并读取真实结果"], tools: ["get_simulation_state", "run_until", "get_road_metrics"], output: "场景与仿真时间、道路速度和延误；缺失指标明确标注。" },
  { name: "traffic-signal-analysis", title: "信号配时分析", description: "依据路口流量、排队与相位数据诊断配时问题。", steps: ["读取路口、周期、相位和时间窗", "分析拥堵与配时约束", "获得授权后修改，并保留恢复方案"], tools: ["get_intersection_metrics", "get_signal_plan", "apply_signal_plan", "restore_signal_plan"], output: "路口诊断与配时建议，注明统计口径和数据来源。" },
  { name: "traffic-scenario-comparison", title: "方案对比评估", description: "检查可比条件，评估基准与候选方案的交通差异。", steps: ["核对路网、需求、统计时段与随机种子", "采集基准和候选方案真实指标", "比较绝对差与相对变化，说明证据范围"], tools: ["capture_metrics", "compare_metrics", "publish_geo_scene"], output: "延误、速度、排队及吞吐量差异；可通过 GIS 展示道路结果。" },
];

export function TrafficSkillsPanel({ onClose }: { onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); } };
    document.addEventListener("keydown", onKey, true);
    return () => { document.removeEventListener("keydown", onKey, true); previous?.focus(); };
  }, [onClose]);
  return <aside className="traffic-skills-panel" aria-label="专属交通技能">
    <header><div><small>TRAFFIC SKILLS</small><strong>专属交通技能</strong></div><button ref={close} type="button" onClick={onClose} aria-label="关闭交通技能">关闭</button></header>
    <p>了解我们研发的交通技能及其工具联动流程。卡片仅用于介绍。</p>
    {skills.map((skill, index) => <article key={skill.name} className="traffic-skill-card" data-expanded={expanded === skill.name}>
      <button type="button" aria-expanded={expanded === skill.name} aria-controls={`skill-${skill.name}`} onClick={() => setExpanded(current => current === skill.name ? null : skill.name)}>
        <span className="traffic-skill-card-head">0{index + 1} · 专属技能</span><strong>{skill.title}</strong><code>{skill.name}</code><p>{skill.description}</p>
      </button>
      <div id={`skill-${skill.name}`} className="traffic-skill-description"><strong>处理步骤</strong><ol>{skill.steps.map(step => <li key={step}>{step}</li>)}</ol><strong>关联工具</strong><div className="traffic-skill-tools">{skill.tools.map(tool => <span key={tool}>{tool}</span>)}</div><strong>预期产出</strong><p>{skill.output}</p><small>实际使用需要加载技能并连接相应 MCP 工具。</small></div>
    </article>)}
  </aside>;
}
