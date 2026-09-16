import assert from "node:assert/strict";
import { chromium } from "playwright";
import { controlCurrentSimulation } from "../lib/simulation-control.ts";
const browser = await chromium.launch({ channel: "msedge" });
try {
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  await page.goto("http://127.0.0.1:30141/abstreet/abstreet.html?../data/system/us/seattle/scenarios/montlake/weekday.bin&--time=08:00:00");
  await page.waitForTimeout(15000);
  const documentId = await page.evaluate(() => performance.timeOrigin);
  async function control(action) {
    await page.evaluate(async ({ source, action }) => {
      await (0, eval)(`(${source})`)(document, action);
    }, { source: controlCurrentSimulation.toString(), action });
  }
  await control("pause");
  await page.waitForTimeout(1000);
  const a = await page.locator("canvas").screenshot({ path: ".next/current-paused.png" });
  await page.waitForTimeout(2000);
  const b = await page.locator("canvas").screenshot();
  assert.ok(a.equals(b), "Pause must freeze the current canvas");
  await control("resume");
  await page.waitForTimeout(2000);
  const c = await page.locator("canvas").screenshot({ path: ".next/current-running.png" });
  assert.ok(!b.equals(c), "Resume must advance the current canvas");
  await control("faster");
  await control("pause");
  await page.waitForTimeout(500);
  const d = await page.locator("canvas").screenshot();
  await page.waitForTimeout(1000);
  assert.ok(d.equals(await page.locator("canvas").screenshot()), "Pause works after changing speed");
  assert.equal(await page.evaluate(() => performance.timeOrigin), documentId, "Control must not reload the page");
  console.log("PASS: synthetic keyboard pauses and resumes the existing WASM simulation");
} finally { await browser.close(); }
