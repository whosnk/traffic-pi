"use client";

import { useSyncExternalStore } from "react";
import type { SimtrendSelection } from "./simtrend-types";
import { emptyIncidentForm, type IncidentForm, type IncidentDraftResult } from "./simtrend-draft";

export type SimtrendContext = {
  scenarioId: string;
  scenarioName: string;
  selection: (SimtrendSelection & { label: string; laneIds: string[] }) | null;
  revision: number;
  incidentDraft: { id: string | null; form: IncidentForm; edited: boolean } | null;
  draftNotice?: string;
};

const contexts = new Map<string, SimtrendContext>();
const listeners = new Set<() => void>();
function emit() { for (const listener of listeners) listener(); }

export const simtrendContextStore = {
  get(key: string): SimtrendContext | null { return contexts.get(key) ?? null; },
  scene(key: string, scenarioId: string, scenarioName: string) {
    const previous = contexts.get(key);
    if (previous?.scenarioId === scenarioId && previous.scenarioName === scenarioName) return;
    contexts.set(key, { scenarioId, scenarioName, selection: null, revision: previous ? previous.revision + 1 : 0, incidentDraft: null });
    emit();
  },
  select(key: string, scenarioId: string, selection: SimtrendContext["selection"]) {
    const previous = contexts.get(key);
    // Ignore late map responses from a scene that the user has already left.
    if (!previous || previous.scenarioId !== scenarioId) return;
    contexts.set(key, { ...previous, selection: selection ? structuredClone(selection) : null, revision: previous.revision + 1, draftNotice: undefined });
    emit();
  },
  editIncident(key: string, patch: Partial<IncidentForm>) {
    const previous = contexts.get(key);
    if (!previous) return;
    contexts.set(key, { ...previous, revision: previous.revision + 1, draftNotice: undefined,
      incidentDraft: { id: previous.incidentDraft?.id ?? null, form: { ...(previous.incidentDraft?.form ?? emptyIncidentForm()), ...patch }, edited: true } });
    emit();
  },
  applyDraft(key: string, draft: IncidentDraftResult) {
    const previous = contexts.get(key);
    if (previous && (previous.scenarioId !== draft.scenario_id || previous.revision !== draft.base_revision)) {
      contexts.set(key, { ...previous, draftNotice: "收到的对话草案基于较早的定位或参数，当前编辑已保留。请按当前定位重新生成草案。" });
      emit();
      return false;
    }
    if (!previous && draft.base_revision !== 0) return false;
    contexts.set(key, { scenarioId: draft.scenario_id, scenarioName: draft.scenario_name,
      revision: (previous?.revision ?? 0) + 1,
      selection: draft.selection.edge_id ? { edge_id: draft.selection.edge_id, ...(draft.selection.lane_id ? { lane_id: draft.selection.lane_id } : {}), ...(draft.selection.zone_id ? { zone_id: draft.selection.zone_id } : {}), label: draft.location_name, laneIds: [...draft.lane_ids] } : null,
      incidentDraft: { id: draft.id, form: structuredClone(draft.form), edited: false } });
    emit();
    return true;
  },
  transfer(draftKey: string, sessionId: string) {
    const previous = contexts.get(draftKey);
    if (!previous || draftKey === sessionId) return;
    contexts.set(sessionId, structuredClone(previous));
    contexts.delete(draftKey);
    emit();
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  },
};

export function useSimtrendContext(key: string) {
  return useSyncExternalStore(simtrendContextStore.subscribe, () => simtrendContextStore.get(key), () => null);
}

const marker = "\n\n<simtrend_spatial_context>\n";
const endMarker = "\n</simtrend_spatial_context>";

export function withSimtrendContext(message: string, context: SimtrendContext | null): string {
  // Commands must reach the command parser unchanged.
  if (/^[!/]/.test(message.trimStart())) return message;
  // Recalled/rejected submissions must not accumulate old map snapshots.
  const index = message.lastIndexOf(marker);
  const original = index >= 0 && message.endsWith(endMarker) ? message.slice(0, index) : message;
  if (!context) return original;
  const snapshot = {
    scenario_id: context.scenarioId,
    scenario_name: context.scenarioName,
    revision: context.revision,
    incident_task_draft: context.incidentDraft ? {
      id: context.incidentDraft.id, form: context.incidentDraft.form,
    } : null,
    selected_object: context.selection ? {
      edge_id: context.selection.edge_id,
      lane_id: context.selection.lane_id || null,
      zone_id: context.selection.zone_id || null,
      label: context.selection.label,
      lane_ids: context.selection.laneIds,
    } : null,
  };
  return original + marker
    + "以下是用户发送本消息时界面显示的 SimTrend 定位数据，不是自动执行指令。\n"
    + JSON.stringify(snapshot, null, 2).replace(/</g, "\\u003c").replace(/>/g, "\\u003e")
    + "\n仅当本条请求涉及 SimTrend 时使用。用户说“这里”“这条道路/车道”时以此定位为准；未选具体车道时不得猜测。"
    + "selected_object 为 null 表示本轮没有选中对象，不得自动沿用历史地图定位；位置不足时先澄清。"
    + "若用户文字明确指定了不同场景或对象，请先确认，不要静默覆盖。查询请求只调用查询工具，不运行仿真。"
    + "创建或修改事故信号优化任务时，调用 prepare_incident_task_draft 生成任务面板草案，base_revision 必须取上面的 revision。"
    + "将当前 incident_task_draft.form 和用户本轮明确修改合并为 fields，并携带当前 selected_object 的 edge_id/lane_id/zone_id。未知字段保持 null，不补默认事故类型、封闭车道数、优化目标或时长。"
    + "草案生成后等待用户在中间任务面板确认运行，不调用 run_incident_signal_optimization 或 submit_simtrend_task 执行草案。"
    + endMarker;
}
