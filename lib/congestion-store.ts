import { useSyncExternalStore } from "react";
import { congestionSteps } from "./congestion";
import type { WorkflowTask } from "./traffic-workflow";
import type { CongestionResult } from "./congestion-executor";
import { mitigationStore } from "./mitigation-store";

export type DetectionTask = WorkflowTask & { result?: CongestionResult };
const tasks = new Map<string, DetectionTask>();
const seen = new Set<string>();
const listeners = new Set<() => void>();
function emit() { for (const listener of listeners) listener(); }
export const congestionStore = {
  get(sessionId: string | null) { return sessionId ? tasks.get(sessionId) ?? null : null; },
  busy() { return [...tasks.values()].some(task => task.status === "running"); },
  start(sessionId: string, id: string, toolName = "detect_congestion") {
    const key = `${sessionId}:${id}`;
    if (seen.has(key)) return false;
    if (mitigationStore.busy()) return false;
    if ([...tasks.values()].some(task => task.status === "running")) return false;
    seen.add(key);
    const startedAt = Date.now();
    tasks.set(sessionId, { sessionId, id, definition: { kind: "congestion", title: "拥堵分析", steps: congestionSteps }, startedAt,
      calls: [{ id, name: toolName, kind: "mcp", startedAt }], stage: 0, stageTimes: { 0: startedAt }, message: "正在打开 A/B Street，等待当前场景就绪…", status: "running" });
    emit(); return true;
  },
  progress(sessionId: string, id: string, stage: number, message: string) {
    const task = this.get(sessionId);
    if (!task || task.id !== id || task.status !== "running" || stage < task.stage) return;
    tasks.set(sessionId, { ...task, stage, stageTimes: { ...task.stageTimes, [stage]: task.stageTimes?.[stage] ?? Date.now() }, message }); emit();
  },
  finish(sessionId: string, id: string, error?: string) {
    const task = this.get(sessionId);
    if (!task || task.id !== id || task.status !== "running") return;
    const endedAt = Date.now();
    const finalStage = task.definition.steps.length - 1;
    tasks.set(sessionId, { ...task, endedAt, stageTimes: error ? task.stageTimes : { ...task.stageTimes, [finalStage]: task.stageTimes?.[finalStage] ?? endedAt }, calls: task.calls.map(call => call.endedAt ? call : { ...call, endedAt, error }), status: error ? "failed" : "completed", stage: error ? task.stage : finalStage, message: error ?? "检测完成，可在对话和分析结果中查看道路排名。" }); emit();
  },
  recordCall(sessionId: string, id: string, action: string, startedAt: number, endedAt?: number, error?: string) {
    const task = this.get(sessionId);
    if (!task || task.id !== id || task.status !== "running") return;
    const callId = `${action}:${startedAt}`;
    const call = { id: callId, name: action, kind: "internal" as const, startedAt, endedAt, error };
    tasks.set(sessionId, { ...task, calls: [...task.calls.filter(item => item.id !== callId), call] }); emit();
  },
  result(sessionId: string, id: string, result: CongestionResult) {
    const task = this.get(sessionId);
    if (!task || task.id !== id || task.status !== "running") return;
    tasks.set(sessionId, { ...task, result }); emit();
  },
  cancel(sessionId: string, message = "检测已中止，请重新检测当前状态。") {
    const task = this.get(sessionId);
    if (!task || task.status !== "running") return;
    const endedAt = Date.now();
    tasks.set(sessionId, { ...task, status: "cancelled", endedAt, message, calls: task.calls.map(call => call.endedAt ? call : { ...call, endedAt, error: message }) }); emit();
    void fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "cancel_detection", sessionId, toolCallId: task.id }) }).catch(() => {});
  },
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
};
export function useCongestionTask(sessionId: string | null) {
  return useSyncExternalStore(congestionStore.subscribe, () => congestionStore.get(sessionId), () => null);
}
