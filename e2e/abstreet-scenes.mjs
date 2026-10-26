import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

const base = process.env.TRAFFIC_PI_BASE_URL || "http://127.0.0.1:30141";
const browser = await chromium.launch({ channel: "msedge" });
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const session = { id: "scene-validation", name: "场景验收", cwd: process.cwd(), projectRoot: process.cwd(), projectKey: process.cwd(), created: "2026-10-25T00:00:00Z", modified: "2026-10-25T00:00:00Z", firstMessage: "场景验收", path: "scene-check.jsonl", messageCount: 1 };
  const errors = [];
  page.on("pageerror", error => { errors.push(error.message); console.log("PAGE", error.stack); });
  page.on("console", message => { if (/panicked|Couldn.t load|Error|Loading .*map|Loading .*scenario/.test(message.text())) console.log(message.text().slice(0,700)); });
  page.on("dialog", dialog => dialog.accept());
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/simulation-demo" || path.startsWith("/api/maplibre/")) return route.continue();
    let json = {};
    if (path === "/api/sessions") json = { sessions: [session], runningSessionIds: [], sessionListVersion: 1 };
    else if (path === "/api/agent/running") json = { sessionIds: [], sessionListVersion: 1 };
    else if (path === `/api/sessions/${session.id}`) json = { info: session, sessionId: session.id, context: { messages: [], entryIds: [], hasMore: false }, tree: [] };
    else if (path === "/api/project-trust") json = { trusted: true, cwd: process.cwd() };
    else if (path === "/api/models") json = { models: {}, modelList: [] };
    else if (path === "/api/worktrees") json = { worktrees: [], isGit: false };
    else if (path === "/api/home") json = { home: process.cwd() };
    else if (path.startsWith("/api/agent/")) json = { state: { isStreaming: false }, success: true, data: [], tools: [], activeTools: [], commands: [] };
    return route.fulfill({ json });
  });
  await page.goto(`${base}/?session=${session.id}`);
  const work = page.getByRole("region", { name: "交通仿真工作台", exact: true });
  const getFrame = () => page.frames().find(frame => frame.url().includes("abstreet.html"));
  const request = (action, params = {}) => getFrame().evaluate(({action, params}) => window.trafficPi.request(action, params), {action, params});
  const waitReady = async map => {
    console.log("Waiting for actual scene", map);
    await page.waitForFunction(map => { const f = document.querySelector('iframe[title="本地交通仿真"]'); return f?.src.includes(`/scenarios/${map}/`) && f.contentWindow?.trafficPi?.ready; }, map, { timeout: 180000 });
    await work.getByText("控制已就绪", {exact: true}).waitFor({timeout: 180000, state:"attached"});
    console.log("Bridge and UI ready", map);
    const state = await request("get_simulation_state");
    assert.ok(state.map.endsWith(`/maps/${map}.bin`), JSON.stringify(state));
    assert.equal(await page.locator('iframe[title="本地交通仿真"]').count(), 1);
    return state;
  };
  const city = await waitReady("yuzhong_core");
  assert.equal(city.paused, true);
  await page.locator(".chat-input-textarea").fill("场景切换保留草稿");
  await work.getByRole("button", { name: "高速公路", exact: true }).click();
  const highway = await waitReady("highway-demo");
  assert.equal(highway.scene, "motorway");
  assert.equal(highway.paused, false);
  assert.equal(highway.speedMultiplier, 1);
  const first = await request("get_road_metrics");
  for (const name of ["高速主线 · 东向", "高速主线 · 西向", "东向入口匝道", "东向出口匝道", "西向入口匝道", "西向出口匝道"]) {
    assert.ok(first.roads.some(road => road.name === name && road.activeVehicles > 0), `No actual vehicles on ${name}`);
  }
  await page.waitForTimeout(6000);
  const moving = await request("get_simulation_state");
  assert.ok(moving.simulationTime > highway.simulationTime + 3, "1× playback must advance actual simulation");
  const second = await request("get_road_metrics");
  assert.notDeepEqual(second.roads, first.roads, "Traffic state must change during playback");
  await mkdir(".next/abstreet-validation", {recursive: true});
  await page.screenshot({path: ".next/abstreet-validation/highway-workspace.png"});
  const firstRun = await work.locator('[role="status"]').first().textContent();
  const frame = getFrame();
  await page.getByRole("navigation", {name: "工作模式"}).getByRole("button", {name: "分析与报告", exact: true}).click();
  await page.getByRole("navigation", {name: "工作模式"}).getByRole("button", {name: "仿真工作台", exact: true}).click();
  assert.equal(getFrame(), frame, "View changes must retain the simulation instance");
  await work.getByRole("button", {name: "Ⅱ 暂停", exact: true}).click();
  await work.getByRole("button", {name: "▶ 继续", exact: true}).waitFor();
  const paused = await request("get_simulation_state");
  await work.getByRole("button", {name: "放大地图", exact: true}).click();
  await work.getByRole("button", {name: "全局", exact: true}).click();
  assert.equal((await request("get_simulation_state")).simulationTime, paused.simulationTime);
  await page.setViewportSize({width: 390, height: 844});
  await page.emulateMedia({reducedMotion: "reduce"});
  await page.waitForTimeout(400);
  await page.getByRole("navigation", {name:"工作模式"}).getByRole("button", {name:"仿真工作台",exact:true}).click();
  for (const name of ["城市交通", "高速公路"]) {
    const button = work.getByRole("button", {name, exact: true});
    const box = await button.boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= 390, `${name} must remain visible on narrow screens`);
    await button.focus();
  }
  await page.screenshot({path: ".next/abstreet-validation/highway-mobile.png"});
  assert.equal(await work.getByRole("alert").count(), 0, "Resizing must not issue camera commands before the canvas has resized");
  await request("run_for", {durationSeconds:2100});
  await work.getByRole("button", {name:"重新播放当前场景",exact:true}).waitFor();
  assert.equal((await request("get_simulation_state")).paused, true, "End of highway demand pauses the actual instance");
  const restarted = await page.evaluate(async () => {
    const response = await fetch('/api/simulation-demo', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'start'})});
    return {status:response.status,body:await response.json()};
  });
  assert.equal(restarted.status, 200, JSON.stringify(restarted));
  assert.equal(restarted.body.result.scenarioId, "abstreet:chongqing-yuzhong", "Legacy start must use the protected city loader");
  const cityAgain = await waitReady("yuzhong_core");
  assert.equal(cityAgain.paused, true);
  assert.ok(Math.abs(cityAgain.simulationTime - city.simulationTime) < 0.2);
  assert.notEqual(await work.locator('[role="status"]').first().textContent(), firstRun);
  await page.setViewportSize({width: 1600, height: 1000});
  await page.getByRole("region", {name: "交通工作区", exact: true}).getByRole("button", {name: "对话", exact: true}).click();
  assert.equal(await page.locator(".chat-input-textarea").inputValue(), "场景切换保留草稿");
  await page.screenshot({path: ".next/abstreet-validation/city-workspace.png"});
  assert.deepEqual(errors, []);
  console.log("PASS actual city → highway → city: distinct identities, mainline/ramp vehicles, 1× motion, single instance, controls, draft, narrow/keyboard/reduced motion", {city, highway, moving});
  // Fault injection only checks error presentation; the scenes above use the deployed WASM.
  for (const resource of ["maps/highway-demo.bin", "scenarios/highway-demo/motorway.bin"]) {
    const pattern = `**/abstreet/data/system/cn/chongqing/${resource}`;
    await page.route(pattern, route => route.fulfill({status:404,body:"Missing test resource"}));
    if (resource.startsWith("maps/")) await work.getByRole("button", {name:"高速公路",exact:true}).click();
    else await work.getByRole("button", {name:"重试",exact:true}).click();
    await work.getByRole("alert").filter({hasText:"场景加载失败"}).getByText(/404/).waitFor();
    assert.equal(await work.locator("iframe").count(), 0, "A missing resource must never retain the old city frame");
    await page.unroute(pattern);
  }
  const html = "**/abstreet/abstreet.html?**";
  await page.route(html, route => route.fulfill({contentType:"text/html",body:'<canvas></canvas><script>window.trafficPi={ready:true,request:async()=>({map:"wrong-map",scene:"motorway",randomSeed:42})};</script>'}));
  await work.getByRole("button", {name:"重试",exact:true}).click();
  await work.getByRole("alert").filter({hasText:"场景加载失败"}).getByText(/身份不匹配/).waitFor();
  await page.unroute(html);
  await page.route(html, route => route.fulfill({contentType:"text/html",body:'<canvas></canvas><script>window.trafficPi={ready:false};</script>'}));
  await page.clock.install();
  await work.getByRole("button", {name:"重试",exact:true}).dispatchEvent("click");
  await work.locator("iframe").waitFor();
  await page.clock.fastForward(180001);
  await work.getByRole("alert").filter({hasText:"场景加载失败"}).getByText(/180 秒/).waitFor();
  assert.equal(await work.locator("iframe").count(), 0);
  console.log("PASS resource 404 (map/demand), identity mismatch and bridge timeout all show explicit errors without old scene fallback");
} finally { await browser.close(); }
