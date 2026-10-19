// Run against the existing dev server: node e2e/simtrend.mjs
import assert from "node:assert/strict";
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const base = process.env.PI_WEB_TEST_URL || "http://127.0.0.1:30141";
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || "msedge" });
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
await mkdir("test-results", { recursive: true });
try {
  await page.goto(base, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "SimTrend 仿真", exact: false }).first().click();
  const panel = page.locator("#traffic-sumo-view");
  await panel.getByLabel("仿真场景").waitFor();
  await panel.getByLabel("仿真场景").selectOption("four_intersections");
  await panel.locator('.simtrend-map[data-ready="true"]').waitFor({ timeout: 30000 });
  const canvas = panel.locator(".simtrend-map canvas");
  const box = await canvas.boundingBox();
  // Two-way horizontal road between the two upper junctions.
  await canvas.click({ position: { x: box.width / 2, y: 28 + (box.height - 56) / 3 + 3 } });
  await panel.locator(".simtrend-selection").waitFor({ timeout: 5000 });
  await panel.getByLabel("搜索道路").fill("e0_c10");
  await panel.getByRole("button", { name: "东北路口东进口 · e0_c10", exact: true }).click();
  await panel.getByRole("button", { name: /车道 1.*e0_c10_1/ }).click();
  const contextTag = page.getByRole("region", { name: "当前对话空间定位" });
  await contextTag.waitFor();
  assert.match(await contextTag.innerText(), /e0_c10_1/);
  await panel.getByRole("button", { name: "已选对象详情", exact: true }).click();
  await panel.locator(".simtrend-result").waitFor({ timeout: 30000 });
  assert.match(await panel.locator(".simtrend-result").innerText(), /e0_c10_1/);
  await panel.getByRole("button", { name: "空间对象与查询", exact: true }).click();
  await panel.getByRole("button", { name: "信号控制范围与相位", exact: true }).click();
  await panel.locator(".simtrend-result").waitFor({ timeout: 30000 });
  assert.match(await panel.locator(".simtrend-result").innerText(), /c10/);
  await panel.getByRole("button", { name: "空间对象与查询", exact: true }).click();
  await panel.locator('.simtrend-map[data-ready="true"]').waitFor({ timeout: 30000 });
  await page.screenshot({ path: "test-results/simtrend-four.png", fullPage: false });
  await panel.getByLabel("仿真场景").selectOption("nanjing_south_ride_hailing");
  assert.doesNotMatch(await contextTag.innerText(), /e0_c10/);
  assert.match(await contextTag.innerText(), /南京南站/);
  await panel.getByLabel("搜索道路").fill("189391594#0");
  await panel.locator(".simtrend-road-search button").first().click();
  assert.match(await contextTag.innerText(), /189391594#0/);
  await contextTag.getByRole("button", { name: "取消空间定位" }).click();
  assert.match(await contextTag.innerText(), /未选择/);
  assert.equal(await panel.locator(".simtrend-selection").count(), 0);
  await panel.getByRole("button", { name: "创建仿真任务", exact: true }).click();
  await panel.getByLabel("任务类型").selectOption("demand");
  await panel.getByLabel("调整对象").selectOption("网约车到站流量");
  await page.screenshot({ path: "test-results/simtrend-demand.png", fullPage: false });
  if (process.env.SIMTREND_E2E_SIMULATE === "1") {
    await panel.getByLabel("仿真时长（秒）", { exact: true }).fill("60");
    await panel.getByRole("button", { name: "创建并运行仿真", exact: true }).click();
    await panel.locator(".simtrend-result").waitFor({ timeout: 180000 });
    assert.match(await panel.locator(".simtrend-result").innerText(), /1.30/);
    await panel.getByRole("button", { name: "播放仿真回放", exact: true }).click();
    await panel.locator(".simtrend-replays img").first().scrollIntoViewIfNeeded();
    await page.waitForFunction(() => [...document.querySelectorAll("#traffic-sumo-view .simtrend-replays img")].some(img => img.complete && img.naturalWidth > 0));
    const replay = await panel.locator(".simtrend-replays img").first().getAttribute("src");
    const response = await page.request.get(base + replay);
    assert.equal(response.status(), 200);
    assert.match((await response.body()).subarray(0, 6).toString(), /^GIF8[79]a$/);
    assert.equal((await page.request.get(base + "/api/simtrend/artifacts/invalid/0")).status(), 404);
    await page.screenshot({ path: "test-results/simtrend-replay.png", fullPage: false });
    console.log("PASS: real Nanjing demand simulation, comparison metrics, GIF HTTP delivery");
  }
  await page.setViewportSize({ width: 430, height: 932 });
  await page.getByRole("button", { name: "SimTrend 仿真", exact: false }).first().click();
  await page.waitForTimeout(400); // Allow the shell's existing responsive transition to settle.
  await page.screenshot({ path: "test-results/simtrend-mobile.png", fullPage: false });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2), false, "page must not overflow horizontally");
  assert.equal(errors.length, 0, errors.join("\n"));
  console.log("PASS: scenes, road/lane selection, queries, demand form, no page errors");
} finally { await browser.close(); }
