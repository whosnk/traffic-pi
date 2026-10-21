import assert from "node:assert/strict";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { chromium } from "playwright";

const candidate = process.env.TRAFFIC_PI_CANDIDATE === "1";
const browser = await chromium.launch({ channel: "msedge" });
try {
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  if (candidate) {
    for (const file of ["game.js", "game_bg.wasm"]) await page.route(`**/wasm_pkg/${file}`, async route => route.fulfill({ body: await readFile(`${process.env.TRAFFIC_PI_CANDIDATE_DIR ?? ".next/abstreet-candidate"}/${file}`), contentType: file.endsWith("wasm") ? "application/wasm" : "text/javascript" }));
  }
  page.on("pageerror", error => console.error("PAGE", error.message));
  await page.goto("http://127.0.0.1:30141/abstreet/abstreet.html?../data/system/cn/chongqing/scenarios/yuzhong_core/weekday.bin&--time=08:00:00");
  await page.waitForFunction(() => window.trafficPi?.ready, null, { timeout: 180000 });
  const request = (action, params = {}) => page.evaluate(({ action, params }) => window.trafficPi.request(action, params), { action, params });
  const initial = await request("get_simulation_state");
  const metrics = await request("get_road_metrics");
  const intersections = await request("get_intersection_metrics");
  console.log("Initial", JSON.stringify(initial), "roads", metrics.roads?.length, "intersections", JSON.stringify(intersections).slice(0, 900));
  const intersectionId = intersections.intersections?.[0]?.intersectionId;
  assert.ok(Number.isInteger(intersectionId));
  const signal = await request("get_signal_plan", { intersectionId });
  console.log("Signal", JSON.stringify(signal));
  await mkdir(".next/abstreet-validation", { recursive: true });
  if (!candidate) await writeFile(".next/abstreet-validation/baseline.json", JSON.stringify({ initial, metrics, intersections, signal }));
  else {
    const baseline = JSON.parse(await readFile(".next/abstreet-validation/baseline.json", "utf8"));
    assert.equal(initial.simulationTime, baseline.initial.simulationTime);
    assert.equal(initial.paused, baseline.initial.paused);
    const requested = await request("get_road_metrics", { roadIds: baseline.metrics.roads.map(road => road.roadId) });
    for (const old of baseline.metrics.roads) {
      const current = requested.roads.find(road => road.roadId === old.roadId);
      assert.ok(current, `Missing road ${old.roadId}`);
      for (const field of ["queueVehicles", "meanVehicleSpeedKph", "meanVehicleDelaySeconds"]) assert.ok(Math.abs(current[field] - old[field]) < 0.001, `Road ${old.roadId} ${field}: ${current[field]} != ${old[field]}`);
    }
    assert.ok(initial.capabilities.includes("traffic-pi-ui-v1"));
    await request("set_native_ui", { enabled: false });
    await page.evaluate(() => { window.viewChanges = 0; window.addEventListener("traffic-pi-view-change", () => window.viewChanges++); });
    const roadId = metrics.roads[0].roadId;
    await request("fit_roads", { roadIds: metrics.roads.slice(0, 5).map(road => road.roadId), smooth: true });
    await page.waitForTimeout(900);
    assert.equal((await request("get_view_state")).moving, false);
    assert.ok(await page.evaluate(() => window.viewChanges > 1), "Camera movement must publish view changes");
    await request("focus_on_road", { roadId, smooth: true });
    await page.waitForTimeout(900);
    const view = await request("get_view_state", { roadId });
    assert.ok(Math.abs(view.anchor.x - view.width / 2) < 1);
    assert.ok(Math.abs(view.anchor.y - view.height / 2) < 1);
    const padding = { left: 40, top: 210, right: 300, bottom: 60 };
    await request("focus_on_road", { roadId, padding });
    const padded = await request("get_view_state", { roadId });
    assert.ok(Math.abs(padded.anchor.x - (view.width + padding.left - padding.right) / 2) < 1);
    assert.ok(Math.abs(padded.anchor.y - (view.height + padding.top - padding.bottom) / 2) < 1);
    await assert.rejects(request("focus_on_road", { roadId, padding: { top: -1 } }), /Invalid top/);
    await assert.rejects(request("fit_roads", { roadIds: [roadId], padding: { top: view.height } }), /no visible area/);
    await request("fit_roads", { roadIds: metrics.roads.slice(0, 5).map(road => road.roadId), padding });
    for (const road of metrics.roads.slice(0, 5)) {
      const fitted = await request("get_view_state", { roadId: road.roadId });
      assert.ok(fitted.anchor.x >= padding.left && fitted.anchor.x <= view.width - padding.right);
      assert.ok(fitted.anchor.y >= padding.top && fitted.anchor.y <= view.height - padding.bottom);
    }
    await request("focus_on_road", { roadId });
    await request("zoom_view", { factor: 1.4 });
    assert.ok((await request("get_view_state")).zoom > view.zoom);
    await request("global_view");
    const global = await request("get_view_state");
    await request("global_view", { padding });
    assert.ok((await request("get_view_state")).zoom < global.zoom, "Global view must fit inside the uncovered map area");
    await request("set_native_ui", { enabled: true });
    assert.equal((await request("get_view_state")).nativeUi, true);
    await request("set_native_ui", { enabled: false });
    await request("focus_on_road", { roadId, smooth: true });
    await request("cancel_camera");
    assert.equal((await request("get_view_state")).moving, false);
    assert.equal((await request("get_simulation_state")).simulationTime, initial.simulationTime);
  }
  const durations = signal.stageDurationsSeconds ?? signal.stages?.map(stage => stage.durationSeconds);
  assert.ok(durations?.length, JSON.stringify(signal));
  const applied = await request("apply_signal_plan", { intersectionId, stageDurationsSeconds: durations.map(d => Math.max(5, Math.round(d + 1))) });
  const restored = await request("restore_signal_plan", { intersectionId });
  console.log("Applied/restored", JSON.stringify(applied).slice(0, 700), JSON.stringify(restored).slice(0, 700));
  const baselineCapture = await request("capture_metrics", { captureId: "parity-base", durationSeconds: 2 });
  const treatmentCapture = await request("capture_metrics", { captureId: "parity-treatment", baselineCaptureId: "parity-base", durationSeconds: 2 });
  const comparison = await request("compare_metrics", { baselineCaptureId: "parity-base", treatmentCaptureId: "parity-treatment" });
  console.log("Capture", JSON.stringify(baselineCapture).slice(0, 2600));
  console.log("Comparison", JSON.stringify(comparison).slice(0, 2600));
  if (!candidate) await writeFile(".next/abstreet-validation/baseline-capture.json", JSON.stringify({ baselineCapture, comparison }));
  else {
    const baseline = JSON.parse(await readFile(".next/abstreet-validation/baseline-capture.json", "utf8"));
    for (const [key, value] of Object.entries(baseline.baselineCapture.metrics)) assert.ok(Math.abs(value - baselineCapture.metrics[key]) < 0.001, `${key}: ${value} != ${baselineCapture.metrics[key]}`);
    assert.equal(comparison.comparable, true);
    for (const change of Object.values(comparison.changes)) assert.equal(change.absoluteChange, 0);
  }
  assert.ok(treatmentCapture && comparison);
  const now = await request("get_simulation_state");
  await request("run_for", { durationSeconds: 1 });
  assert.equal((await request("get_simulation_state")).simulationTime, now.simulationTime + 1);
  await page.screenshot({ path: `.next/abstreet-validation/${candidate ? "candidate" : "original"}.png` });
  console.log(`PASS ${candidate ? "candidate" : "original"} control and workflow bridge`);
} finally { await browser.close(); }
