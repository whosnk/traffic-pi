"use client";

import { useEffect, useRef, useState } from "react";
import { workflowStepState, type WorkflowTask } from "@/lib/traffic-workflow";
import styles from "./TrafficWorkflow.module.css";

export function TrafficWorkflow({ task, onStart }: { task: WorkflowTask | null; onStart: () => void }) {
  const list = useRef<HTMLOListElement>(null);
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (task?.status !== "running") return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [task?.status]);
  useEffect(() => {
    const element = list.current;
    const step = element?.querySelector<HTMLElement>('[aria-current="step"]');
    if (element && step) element.scrollTo({ left: Math.max(0, step.offsetLeft - element.offsetLeft - element.clientWidth / 2 + step.clientWidth / 2), behavior: "instant" });
  }, [task?.stage]);
  const status = task ? { running: "执行中", completed: "已完成", failed: "执行失败", cancelled: "已取消" }[task.status] : "等待任务";
  const elapsed = task ? Math.max(0, Math.floor(((task.endedAt ?? Math.max(now, task.startedAt)) - task.startedAt) / 1000)) : 0;
  return <section className={styles.workflow} aria-label="技能执行流程" data-status={task?.status ?? "idle"}>
    <header><div><small>技能流程</small><strong>{task?.definition.title ?? "等待任务"}</strong></div><span className={styles.status}>{status}{task && ` · ${elapsed}s`}</span><button type="button" disabled={task?.status === "running"} onClick={onStart}>{task ? task.status === "failed" || task.status === "cancelled" ? "重新检测" : "再次检测" : "检测当前拥堵点"}</button></header>
    {task ? <ol ref={list} tabIndex={0} aria-label="执行阶段">{task.definition.steps.map((label, index) => {
      const state = workflowStepState(task, index);
      const time = task.stageTimes?.[index];
      return <li key={`${index}:${label}`} data-state={state} aria-current={state === "running" ? "step" : undefined}><time dateTime={time ? new Date(time).toISOString() : undefined}>{time ? new Date(time).toLocaleTimeString("zh-CN", { hour12: false }) : "--:--:--"}</time><span className={styles.node} aria-hidden="true">{state === "completed" ? "✓" : state === "failed" ? "!" : index + 1}</span><b>{label}</b><small>{{ waiting: "待执行", running: "进行中", completed: "已完成", failed: "失败", cancelled: "已取消" }[state]}</small></li>;
    })}</ol> : <div className={styles.empty}>通过对话或交通技能开始任务，执行阶段将在这里持续展示。</div>}
    <div className={styles.message}><span role="status" aria-live="polite">{task?.message ?? "通过对话或交通技能开始分析"}</span>
      <details onKeyDown={event => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); } }}><summary>工具详情{task ? ` · ${task.calls.length}` : ""}</summary><div className={styles.details}>
        <strong>真实执行记录</strong><p>MCP 调用及其内部操作分开记录。</p>
        {!task && <p>尚无工具调用。</p>}
        {task?.calls.map(call => <div key={call.id}><small>{call.kind === "mcp" ? "MCP 调用" : "内部操作"}</small><code>{call.name}</code><span>{call.error ? "失败／中止" : call.endedAt ? "成功" : "执行中"} · {Math.max(0, ((call.endedAt ?? Math.max(now, call.startedAt)) - call.startedAt) / 1000).toFixed(1)}s</span>{call.error && <p>{call.error}</p>}</div>)}
      </div></details>
    </div>
  </section>;
}
