import { useSyncExternalStore } from "react";
import { chongqingScenario, scenarioActionReason } from "./traffic-scenarios";

export type SimulationScope = { scenarioId?: string; runId?: string };
type Runtime = { scenarioId: string; runId: string; status: "idle" | "loading" | "ready" | "failed" | "ended"; error: string };
const initial: Runtime = { scenarioId: chongqingScenario.id, runId: "", status: "idle", error: "" };
let current = initial;
const listeners = new Set<() => void>();
export const abstreetRuntime = {
  get() { return current; },
  load(scenarioId: string) { current = { scenarioId, runId: crypto.randomUUID(), status: "loading", error: "" }; this.emit(); return current; },
  update(runId: string, status: Runtime["status"], error = "") { if (current.runId !== runId) return; current = { ...current, status, error }; this.emit(); },
  matches(scope: SimulationScope) { return !!scope.runId && scope.runId === current.runId && scope.scenarioId === current.scenarioId; },
  actionReason(action: string, scope?: SimulationScope) {
    if (scope && !this.matches(scope)) return "该结果属于其他场景或旧运行批次，请在当前场景重新检测；历史结果仍可查看。";
    return scenarioActionReason(current.scenarioId, action) || (current.status === "loading" ? "场景正在加载，请等待控制接口就绪。" : current.status === "failed" ? current.error : "");
  },
  emit() { for (const listener of listeners) listener(); },
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
};
export function useAbstreetRuntime() { return useSyncExternalStore(abstreetRuntime.subscribe, abstreetRuntime.get, () => initial); }
