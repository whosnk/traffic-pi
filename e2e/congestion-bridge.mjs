import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ channel: "msedge" });
try {
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  page.on("console", message => { if (message.type() === "error") console.error(message.text()); });
  await page.goto("http://127.0.0.1:30141/abstreet/abstreet.html?../data/system/cn/chongqing/scenarios/yuzhong_core/weekday.bin&--time=08:00:00");
  await page.waitForFunction(() => window.trafficPi?.ready, null, { timeout: 180000 });
  const request = (action, params = {}) => page.evaluate(({ action, params }) => window.trafficPi.request(action, params), { action, params });
  const initial = await request("get_simulation_state");
  console.log("Initial state", JSON.stringify(initial));
  const metrics = await request("get_road_metrics");
  console.log("Metrics sample", JSON.stringify(metrics).slice(0, 2200));
  for (const action of ["pause", "resume", "faster", "faster"]) {
    await request(action);
    const before = await request("get_simulation_state");
    await page.waitForTimeout(400);
    await request("get_road_metrics");
    const roadId = metrics.roads?.[0]?.roadId;
    assert.ok(Number.isInteger(roadId), "Road metrics must expose a stable road ID");
    await request("highlight_roads", { roads: [{ roadId, level: "warning" }] });
    await request("focus_on_road", { roadId });
    await request("clear_highlights");
    const after = await request("get_simulation_state");
    assert.equal(after.paused, before.paused);
    assert.equal(after.speedMultiplier, before.speedMultiplier);
    if (before.paused) assert.equal(after.simulationTime, before.simulationTime);
    else assert.ok(after.simulationTime > before.simulationTime, "Queries must not stall a running simulation");
    console.log("Preserved", action, JSON.stringify(after));
  }
  console.log("PASS: real bridge queries/highlight/focus preserve pause, running and speed states without arrow key wakeup");
} finally { await browser.close(); }
