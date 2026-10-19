// Verify an existing completed incident run without starting another simulation.
import assert from "node:assert/strict";
import { readFile, readdir, mkdir } from "node:fs/promises";
import { chromium } from "playwright";
const base = process.env.PI_WEB_TEST_URL || "http://127.0.0.1:30141";
const jobsPath = "integrations/simtrend/.runtime/jobs";
const jobs = await Promise.all((await readdir(jobsPath)).filter(name => name.endsWith(".json")).map(async name => JSON.parse(await readFile(`${jobsPath}/${name}`, "utf8"))));
const original = jobs.filter(job => job.tool === "run_incident_signal_optimization" && job.status === "completed" && job.result?.run_root)
  .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
assert.ok(original, "Run an incident simulation once before this replay-only check");
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || "msedge" });
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
await page.route("**/api/simtrend", route => {
  const body = route.request().postDataJSON();
  // Deliberately render the saved, unfiltered payload to test old chat results too.
  if (body.action === "jobs") return route.fulfill({ json: { ok: true, jobs: [original] } });
  if (body.action === "start") throw new Error("This check must not start a simulation");
  return route.continue();
});
try {
  const response = await page.request.post(base + "/api/simtrend", { data: { action: "job", job_id: original.id } });
  assert.equal(response.status(), 200);
  const { job } = await response.json();
  const replays = job.artifacts.filter(item => item.kind === "replay");
  assert.equal(replays.length, 2);
  for (const replay of replays) assert.equal((await page.request.get(base + replay.url)).status(), 200);
  await page.goto(base, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "SimTrend 仿真", exact: false }).first().click();
  const panel = page.locator("#traffic-sumo-view");
  await panel.getByLabel("仿真场景").selectOption(original.arguments.scenario_id);
  await panel.getByRole("button", { name: "运行记录与回放", exact: true }).click();
  await panel.getByRole("button", { name: "播放仿真回放", exact: true }).click();
  const figures = panel.locator(".simtrend-replays figure");
  assert.equal(await figures.count(), 2);
  assert.deepEqual(await figures.locator("figcaption").allTextContents(), ["基线方案", "优化方案"]);
  assert.equal(await panel.locator(".simtrend-downloads a").count(), job.artifacts.length);
  await figures.last().scrollIntoViewIfNeeded();
  await page.waitForFunction(() => [...document.querySelectorAll("#traffic-sumo-view .simtrend-replays img")].every(img => img.complete && img.naturalWidth > 0));
  await mkdir("test-results", { recursive: true });
  await page.screenshot({ path: "test-results/simtrend-replays-scoped.png" });
  assert.equal(errors.length, 0, errors.join("\n"));
  console.log(`PASS: existing run ${original.id}, backend and legacy UI both show exactly 2 replays and ${job.artifacts.length} related downloads; GIF URLs work; no simulation started`);
} finally { await browser.close(); }
