"use client";

import type { MitigationTask } from "@/lib/mitigation-store";
import type { Observation } from "@/lib/mitigation";
import styles from "./SignalControlDetails.module.css";

export function SignalControlDetails({ task, onPreview, onFocus }: { task: MitigationTask; onPreview: (stage?: number) => void; onFocus: (roadId: number) => void }) {
  const original = task.originalPlan;
  const live = task.liveSignal;
  const selected = task.candidates.find(candidate => candidate.id === task.selectedId);
  const baseline = task.baselineSamples ?? task.comparison?.baselineSamples ?? [];
  const candidate = task.candidateSamples ?? task.comparison?.candidateSamples ?? [];
  const approaches = task.context?.approaches ?? [];
  const cycle = original?.stages.reduce((sum, stage) => sum + stage.durationSeconds, 0) ?? 1;
  const active = ["running","awaiting_selection","awaiting_decision"].includes(task.status);
  const graph = (samples: Observation[], roadId: number, max: number) => samples.map(sample => {
    const queue = sample.approaches.find(approach => approach.roadId === roadId)?.queueVehicles;
    return queue === undefined ? null : `${24 + (sample.simulationTime - samples[0].simulationTime) / 300 * 264},${91 - queue / max * 72}`;
  }).filter(Boolean).join(" ");
  return <div className={styles.signalDetails}>
    <section aria-label="实时信号状态">
      <h3>路口 {task.context?.intersectionId ?? "待确定"} · 实际通行状态</h3>
      <p role="status">{task.signalError || (!active ? "任务已结束 · 以下保留本轮采集与配时记录" : live ? `相位 ${live.currentStage + 1} · 剩余 ${live.stageRemainingSeconds?.toFixed(1) ?? "未提供"} 秒 · 仿真时刻 ${live.simulationTime?.toFixed(1) ?? "未提供"} 秒` : "等待控制桥读取信号状态")}</p>
      <div className={styles.legend}><span>🟢 保护放行</span><span>🟠 虚线 · 让行</span><span>🔴 禁止通行</span></div>
      {task.planApplied && <strong className={styles.applied}>新方案已生效 · 已读取核对</strong>}
      {task.previewStage !== undefined && <p className={styles.preview}>预览 · 未应用 · 相位 {task.previewStage + 1}<button type="button" onClick={() => onPreview()}>退出预览</button></p>}
      <div className={styles.phaseList}>{(original ?? task.context?.signal)?.stages.map((stage, index) => <button key={index} type="button" disabled={!active} aria-pressed={task.previewStage === index} onClick={() => onPreview(index)} data-active={live?.currentStage === index}>
        相位 {index + 1}{live?.currentStage === index ? " · 当前" : ""}<small>{[...new Set(stage.movements.filter(movement => !movement.crosswalk).map(movement => `${movement.fromRoadId} → ${movement.toRoadId}`))].join("、") || "行人通行"}</small>
      </button>)}</div>
    </section>
    {!!baseline.length && <section aria-label="验证排队曲线"><h3>排队响应 · 原配时 / 新配时</h3><p>横轴为各轮已推进的仿真秒数，纵轴为排队车辆。未采样部分留空。</p><div className={styles.legend}><span className={styles.baselineKey}>━ 原配时</span><span className={styles.candidateKey}>━ 新配时</span></div>
      {approaches.map(approach => {
        const values = [...baseline, ...candidate].map(sample => sample.approaches.find(item => item.roadId === approach.roadId)?.queueVehicles ?? 0);
        const max = Math.max(5, ...values);
        const latest = (candidate.length ? candidate : baseline).at(-1)?.approaches.find(item => item.roadId === approach.roadId);
        return <figure key={approach.roadId} className={styles.queueFigure}>
          <figcaption><button type="button" disabled={!active} onClick={() => onFocus(approach.roadId)}>{approach.roadId === task.targetRoadId ? "目标方向" : "其他进口"} · {approach.name === "???" ? `道路 ${approach.roadId}` : approach.name} ({approach.roadId}) ↗</button><small>最近采样 {latest?.queueVehicles ?? "未提供"} 辆</small></figcaption>
          <svg viewBox="0 0 310 115" role="img" aria-label={`道路 ${approach.roadId} 排队曲线，原配时 ${baseline.length} 个样本，新配时 ${candidate.length} 个样本`}>
            <path d="M24 16V91H288" className={styles.axis} /><path d="M24 55H288" className={styles.gridLine} />
            <text x="0" y="22">{max}</text><text x="10" y="94">0</text><text x="24" y="108">0</text><text x="142" y="108">150</text><text x="267" y="108">300s</text>
            <polyline points={graph(baseline, approach.roadId, max)} className={styles.baselineLine} /><polyline points={graph(candidate, approach.roadId, max)} className={styles.candidateLine} />
          </svg>
        </figure>;
      })}
    </section>}
    {original && <section aria-label="配时方案对照"><h3>配时调整 · 周期 {cycle.toFixed(0)} 秒</h3><p>灰色为原配时，青绿为候选；所有条形共用 {cycle.toFixed(0)} 秒尺度。预览不改变当前灯态。</p>
      {(task.status === "awaiting_selection" ? task.candidates : selected ? [selected] : []).map(plan => <div key={plan.id} className={styles.timingPlan}><strong>{plan.title}</strong>{original.stages.map((stage, index) => <div key={index} className={styles.timingRow}>
        <button type="button" disabled={!active} onClick={() => onPreview(index)}>相位 {index + 1} · 预览</button><span>{stage.durationSeconds}s → {plan.durations[index]}s（{plan.durations[index] - stage.durationSeconds > 0 ? "+" : ""}{plan.durations[index] - stage.durationSeconds}s）</span>
        <div className={styles.bar} aria-label={`相位 ${index + 1} 原配时 ${stage.durationSeconds} 秒`}><i style={{ width: `${stage.durationSeconds / cycle * 100}%` }} /></div>
        <div className={`${styles.bar} ${styles.candidateBar}`} aria-label={`候选配时 ${plan.durations[index]} 秒`}><i style={{ width: `${plan.durations[index] / cycle * 100}%` }} /></div>
      </div>)}</div>)}
    </section>}
  </div>;
}
