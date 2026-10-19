// Verifies the outgoing chat request without sending anything to an LLM.
import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || "msedge" });
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
const prompts = [];
const errors = [];
page.on("pageerror", error => errors.push(error.message));
await page.route("**/api/agent/**", async route => {
  const path = new URL(route.request().url()).pathname;
  if (path.endsWith("/new")) return route.fulfill({ json: { sessionId: "simtrend-context-test" } });
  if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: 'data: {"type":"connected","sessionId":"simtrend-context-test","isStreaming":false}\n\n' });
  if (route.request().method() === "POST") {
    const command = route.request().postDataJSON();
    if (command.type === "prompt") {
      prompts.push(command.message);
      return route.fulfill({ status: 400, json: { error: "Test intercepted: no model was called", code: "prompt_rejected", accepted: false } });
    }
    return route.fulfill({ json: { success: true, data: {} } });
  }
  return route.fulfill({ json: { running: false, sessionIds: [] } });
});
try {
  await page.goto(process.env.PI_WEB_TEST_URL || "http://127.0.0.1:30141", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "SimTrend 仿真", exact: false }).first().click();
  const panel = page.locator("#traffic-sumo-view");
  await panel.getByLabel("仿真场景").selectOption("four_intersections");
  await panel.getByLabel("搜索道路").fill("e0_c10");
  await panel.getByRole("button", { name: "东北路口东进口 · e0_c10", exact: true }).click();
  await panel.getByRole("button", { name: /车道 1.*e0_c10_1/ }).click();
  const input = page.locator("textarea.chat-input-textarea").first();
  await input.fill("查询这条车道的详细信息，不运行仿真");
  await input.press("Enter");
  await page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/api/agent/simtrend-context-test"));
  assert.equal(prompts.length, 1);
  assert.match(prompts[0], /"scenario_id": "four_intersections"/);
  assert.match(prompts[0], /"lane_id": "e0_c10_1"/);
  assert.match(prompts[0], /^查询这条车道/);
  await panel.getByLabel("仿真场景").selectOption("nanjing_south_ride_hailing");
  await input.fill("查询当前场景，不运行仿真");
  await input.press("Enter");
  await page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/api/agent/simtrend-context-test"));
  assert.equal(prompts.length, 2);
  assert.match(prompts[1], /"scenario_id": "nanjing_south_ride_hailing"/);
  assert.match(prompts[1], /"selected_object": null/);
  assert.doesNotMatch(prompts[1], /e0_c10/);
  assert.equal(errors.length, 0, errors.join("\n"));
  console.log("PASS: actual composer sends scene/lane snapshot, scene change removes old IDs; all model calls intercepted");
} finally { await browser.close(); }
