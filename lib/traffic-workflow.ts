import { abstreetRuntime } from "./abstreet-runtime";

export type WorkflowDefinition = { kind: string; title: string; steps: readonly string[] };
export type WorkflowCall = { id: string; name: string; kind: "mcp" | "internal"; startedAt: number; endedAt?: number; error?: string };
export type WorkflowTask = {
  scenarioId?: string;
  runId?: string;
  sessionId: string;
  id: string;
  definition: WorkflowDefinition;
  stage: number;
  stageTimes?: Record<number, number>;
  message: string;
  status: "running" | "failed" | "completed" | "cancelled" | "awaiting_selection" | "awaiting_decision" | "restoring";
  startedAt: number;
  endedAt?: number;
  calls: WorkflowCall[];
};

export function workflowStepState(task: WorkflowTask | null, index: number): "waiting" | "running" | "completed" | "failed" | "cancelled" {
  if (!task) return "waiting";
  if (index < task.stage || (task.status === "completed" && index === task.stage)) return "completed";
  if (index === task.stage) return task.status === "failed" || task.status === "cancelled" ? task.status : "running";
  return "waiting";
}

export function startCongestionAnalysis(sessionId: string | null) {
  const reason = abstreetRuntime.actionReason("detect_congestion");
  if (reason) { window.dispatchEvent(new CustomEvent("traffic-action-error", { detail: reason })); return false; }
  const detail = { sessionId, handled: false };
  const accepted = window.dispatchEvent(new CustomEvent("traffic-start-congestion", { detail, cancelable: true }));
  return accepted && detail.handled;
}
