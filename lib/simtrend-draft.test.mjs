import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const jiti = createJiti(import.meta.url);
const { simtrendContextStore: store, withSimtrendContext } = await jiti.import("./simtrend-context.ts");
const { incidentDraftIssues } = await jiti.import("./simtrend-draft.ts");
const { trafficResultFromMessage } = await jiti.import("./traffic-results.ts");
const draft = () => ({ type: "simtrend-task-draft", ok: true, id: "draft-1", base_revision: 0,
  scenario_id: "four", scenario_name: "Four", selection: { edge_id: "east", lane_id: "east_1" },
  location_name: "East", lane_ids: ["east_0", "east_1"], missing_fields: [], warnings: [], ready: true,
  form: { incident_type: "追尾事故", incident_duration_minutes: 10, lane_closure_count: 1, objective: "优先缓解排队", duration_seconds: 600 } });

test("MCP draft results reach the UI without being counted as simulation results", () => {
  const parsed = trafficResultFromMessage({ role: "toolResult", toolCallId: "draft-call", toolName: "mcp_simtrend_prepare_incident_task_draft_abcdef012345", content: [], details: { structuredContent: draft() } });
  assert.equal(parsed.type, "simtrend_draft");
  assert.equal(store.applyDraft("draft-session", parsed.data), true);
  assert.equal(store.get("draft-session").selection.lane_id, "east_1");
  store.editIncident("draft-session", { incident_duration_minutes: 15 });
  assert.equal(store.get("draft-session").incidentDraft.form.incident_duration_minutes, 15);
  const sent = withSimtrendContext("改为仿真900秒", store.get("draft-session"));
  assert.match(sent, /"incident_duration_minutes": 15/);
  assert.match(sent, /"revision": 2/);
  assert.match(sent, /prepare_incident_task_draft/);
});

test("late drafts cannot overwrite a changed location or hand-edited parameter", () => {
  store.scene("late-draft", "four", "Four");
  store.editIncident("late-draft", { duration_seconds: 900 });
  assert.equal(store.applyDraft("late-draft", draft()), false);
  assert.equal(store.get("late-draft").incidentDraft.form.duration_seconds, 900);
  store.scene("late-draft", "nanjing", "Nanjing");
  assert.equal(store.applyDraft("late-draft", { ...draft(), base_revision: store.get("late-draft").revision }), false);
  assert.equal(store.get("late-draft").scenarioId, "nanjing");
  assert.equal(store.get("late-draft").incidentDraft, null);
});

test("confirmation requires exact lane and all bounded parameters", () => {
  const value = draft();
  assert.deepEqual(incidentDraftIssues(value.form, value.selection, 2), []);
  assert.ok(incidentDraftIssues({ ...value.form, duration_seconds: null }, value.selection, 2).includes("请填写仿真时长"));
  assert.ok(incidentDraftIssues(value.form, { edge_id: "east" }, 2).includes("请选择具体事故车道"));
  assert.equal(incidentDraftIssues({ ...value.form, lane_closure_count: 3 }, value.selection, 2).length, 1);
});
