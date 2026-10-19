import type { SimtrendSelection } from "./simtrend-types";

export type IncidentForm = {
  incident_type: string | null;
  incident_duration_minutes: number | null;
  lane_closure_count: number | null;
  objective: string | null;
  duration_seconds: number | null;
};
export type IncidentDraftResult = {
  type: "simtrend-task-draft"; ok: true; id: string; base_revision: number;
  scenario_id: string; scenario_name: string; selection: Partial<SimtrendSelection>;
  location_name: string; lane_ids: string[]; form: IncidentForm;
  missing_fields: string[]; warnings: string[]; ready: boolean; message: string;
};
export const emptyIncidentForm = (): IncidentForm => ({
  incident_type: null, incident_duration_minutes: null, lane_closure_count: null,
  objective: null, duration_seconds: null,
});

export function incidentDraftIssues(form: IncidentForm, selection: SimtrendSelection | null, laneCount: number): string[] {
  const issues: string[] = [];
  if (!selection?.edge_id) issues.push("请选择事故道路");
  if (!selection?.lane_id) issues.push("请选择具体事故车道");
  if (!["追尾事故", "碰撞事故", "车辆抛锚"].includes(form.incident_type ?? "")) issues.push("请选择事件类型");
  if (!["优先缓解排队", "优先降低等待时间"].includes(form.objective ?? "")) issues.push("请选择优化目标");
  for (const [key, label, minimum, maximum] of [
    ["incident_duration_minutes", "持续时间", 1, 180],
    ["lane_closure_count", "封闭车道数", 1, Math.min(8, laneCount || 8)],
    ["duration_seconds", "仿真时长", 60, 3600],
  ] as const) {
    const value = form[key];
    if (value == null) issues.push(`请填写${label}`);
    else if (!Number.isInteger(value) || value < minimum || value > maximum) issues.push(`${label}须为 ${minimum}–${maximum} 之间的整数`);
  }
  return issues;
}
