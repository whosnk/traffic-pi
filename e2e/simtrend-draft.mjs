// Real draft validation + simulated model tool events. No paid model or simulation runs.
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
const base = process.env.PI_WEB_TEST_URL || "http://127.0.0.1:30141";
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || "msedge" });
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
page.setDefaultTimeout(20000);
const prompts = [], starts = [], errors = [];
const sid = "simtrend-draft-e2e";
let created = true;
page.on("pageerror", error => errors.push(error.message));
await page.addInitScript(() => {
  const sources = [];
  window.EventSource = class {
    readyState = 1;
    constructor(url) {
      this.url = url; sources.push(this);
      setTimeout(() => this.onmessage?.({ data: JSON.stringify({ type: "connected", isStreaming: false }) }), 0);
    }
    close() { this.readyState = 2; }
  };
  window.emitDraftTestEvent = event => sources.filter(source => source.readyState === 1).forEach(source => source.onmessage?.({ data: JSON.stringify(event) }));
});
await page.route("**/api/agent/**", async route => {
  if (route.request().url().endsWith("/new")) { created = true; return route.fulfill({ json: { sessionId: sid } }); }
  if (route.request().method() === "POST") {
    const command = route.request().postDataJSON();
    if (command.type === "prompt") prompts.push(command.message);
    return route.fulfill({ json: { success: true, data: {} } });
  }
  return route.fulfill({ json: { running: false, sessionIds: [] } });
});
await page.route("**/api/sessions**", route => {
  const path = new URL(route.request().url()).pathname;
  if (path === "/api/sessions") return route.fulfill({ json: { sessions: created ? [{ id: sid, path: "", cwd: process.cwd(), transient: true, name: "Draft test", firstMessage: "Draft test", created: new Date().toISOString(), modified: new Date().toISOString(), messageCount: 1 }] : [], runningSessionIds: [] } });
  return route.fulfill({ status: 404, json: { error: "Test session is in memory only" } });
});
await page.route("**/api/simtrend", async route => {
  const body = route.request().postDataJSON();
  if (body.action !== "start") return route.continue();
  starts.push(body);
  return route.fulfill({ json: { ok: true, job: { id: "mock-confirmed-job", title: "事件处置与信号优化", tool: "run_incident_signal_optimization", arguments: { scenario_id: "four_intersections" }, status: "completed", created_at: new Date().toISOString(), steps: [], artifacts: [] } } });
});
const snapshot = prompt => JSON.parse(prompt.split("<simtrend_spatial_context>\n")[1].split("\n仅当")[0].split("\n").slice(1).join("\n"));
async function send(text) {
  const count = prompts.length;
  await page.locator("textarea.chat-input-textarea").first().fill(text);
  const submitted = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith(`/api/agent/${sid}`));
  await page.locator("textarea.chat-input-textarea").first().press("Enter");
  await page.waitForFunction(() => new URL(location.href).searchParams.has("session"));
  await submitted;
  assert.equal(prompts.length, count + 1);
  return snapshot(prompts.at(-1));
}
async function deliver(fields, revision, callId) {
  const response = await page.request.post(base + "/api/simtrend", { data: { action: "incident_draft", scenario_id: "four_intersections", fields, base_revision: revision } });
  assert.equal(response.status(), 200);
  const draft = await response.json();
  await page.evaluate(({ draft, callId }) => {
    window.emitDraftTestEvent({ type: "tool_execution_end", toolCallId: callId, toolName: "mcp_simtrend_prepare_incident_task_draft_abcdef012345", result: { structuredContent: draft }, isError: false });
    window.emitDraftTestEvent({ type: "prompt_done" });
  }, { draft, callId });
  return draft;
}
try {
  await page.goto(base + "?session=" + sid, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "SimTrend 仿真", exact: false }).first().click();
  const panel = page.locator("#traffic-sumo-view");
  await panel.getByLabel("仿真场景").selectOption("four_intersections");
  await panel.getByLabel("搜索道路").fill("e0_c10");
  await panel.getByRole("button", { name: "东北路口东进口 · e0_c10", exact: true }).click();
  await panel.getByRole("button", { name: /车道 1.*e0_c10_1/ }).click();
  const first = await send("这里发生追尾事故，封闭10分钟，帮我生成信号优化任务草案");
  await deliver({ edge_id: "e0_c10", lane_id: "e0_c10_1", incident_type: "追尾事故", incident_duration_minutes: 10 }, first.revision, "first-draft");
  await panel.getByRole("region", { name: "事件任务草案" }).waitFor();
  const confirm = panel.getByRole("button", { name: "确认草案并运行仿真" });
  assert.equal(await confirm.isDisabled(), true);
  assert.equal(await panel.getByLabel("仿真时长（秒）", { exact: true }).inputValue(), "");
  assert.equal(starts.length, 0);
  await panel.getByLabel("封闭车道数", { exact: true }).fill("1");
  await panel.getByLabel("优化目标").selectOption("优先缓解排队");
  await panel.getByLabel("仿真时长（秒）", { exact: true }).fill("600");
  assert.equal(await confirm.isEnabled(), true);
  const second = await send("把仿真时长改成900秒，其他参数不变，仍然只更新草案");
  assert.equal(second.incident_task_draft.form.duration_seconds, 600);
  assert.equal(second.incident_task_draft.form.lane_closure_count, 1);
  await deliver({ ...second.incident_task_draft.form, edge_id: second.selected_object.edge_id, lane_id: second.selected_object.lane_id, duration_seconds: 900 }, second.revision, "second-draft");
  await page.waitForFunction(() => document.querySelector('#traffic-sumo-view input[max="3600"]')?.value === "900");
  assert.equal(starts.length, 0);
  await mkdir("test-results", { recursive: true });
  await page.screenshot({ path: "test-results/simtrend-draft.png" });
  await confirm.click();
  await panel.getByRole("heading", { name: "事件处置与信号优化", exact: true }).waitFor();
  assert.equal(starts.length, 1);
  assert.equal(starts[0].form.duration_seconds, 900);
  assert.equal(starts[0].selection.lane_id, "e0_c10_1");
  assert.equal(starts[0].draft_mode, true);
  assert.equal(errors.length, 0, errors.join("\n"));
  console.log("PASS: chat tool event opens editable draft, unknown fields stay blank, manual changes reach next prompt, second draft updates form, explicit confirmation submits exact values; no model/simulation called");
} catch (error) {
  console.error("Browser state:", page.url(), (await page.locator("#traffic-sumo-view").innerText()).slice(-4000), errors);
  await page.screenshot({ path: "test-results/simtrend-draft-failure.png" });
  throw error;
} finally { await browser.close(); }
