export type WorkflowDefinition = { kind: string; title: string; steps: readonly string[] };
export type WorkflowCall = { id: string; name: string; kind: "mcp" | "internal"; startedAt: number; endedAt?: number; error?: string };
export type WorkflowTask = {
  sessionId: string;
  id: string;
  definition: WorkflowDefinition;
  stage: number;
  stageTimes?: Record<number, number>;
  message: string;
  status: "running" | "failed" | "completed" | "cancelled";
  startedAt: number;
  endedAt?: number;
  calls: WorkflowCall[];
};

export function workflowStepState(task: WorkflowTask | null, index: number) {
  if (!task) return "waiting";
  if (task.status === "completed" || index < task.stage) return "completed";
  if (index === task.stage) return task.status === "running" ? "running" : task.status;
  return "waiting";
}

export function startCongestionAnalysis(sessionId: string | null) {
  const detail = { sessionId, handled: false };
  const accepted = window.dispatchEvent(new CustomEvent("traffic-start-congestion", { detail, cancelable: true }));
  return accepted && detail.handled;
}
