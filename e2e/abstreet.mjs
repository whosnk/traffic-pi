import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ channel: "msedge" });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("http://127.0.0.1:30141/?cwd=" + encodeURIComponent(process.cwd()));
  const entry = page.getByRole("button", { name: "▧ 仿真工作台 · A/B Street", exact: true });
  await entry.click();
  const dialog = page.getByRole("region", { name: "A/B Street 仿真工作台" });
  const frame = page.frameLocator('iframe[title="A/B Street 本地仿真"]');
  await frame.locator("canvas").waitFor({ timeout: 60000 });
  await page.locator(".chat-input-textarea").fill("比较当前场景的交通方案");
  assert.equal(await page.locator(".chat-input-textarea").inputValue(), "比较当前场景的交通方案");
  assert.ok(await page.locator("iframe").evaluate((element) => element.clientWidth >= 1500));
  const chat = await page.locator(".traffic-chat-column").boundingBox();
  const simulation = await dialog.boundingBox();
  assert.ok(chat.width >= 360 && simulation.width > 800);
  assert.ok(chat.x + chat.width <= simulation.x);
  assert.equal(await page.locator("dialog[open]").count(), 0);
  const originalFrame = page.frames().find((item) => item.url().includes("abstreet.html"));
  await page.getByRole("button", { name: "切换全屏" }).click();
  await page.waitForFunction(() => document.fullscreenElement !== null);
  await page.getByRole("button", { name: "切换全屏" }).click();
  await page.getByRole("button", { name: "收起仿真" }).click();
  await dialog.waitFor({ state: "hidden" });
  await page.getByRole("button", { name: /Show sidebar|显示侧边栏/ }).click();
  await entry.click();
  assert.equal(page.frames().find((item) => item.url().includes("abstreet.html")), originalFrame);
  await page.screenshot({ path: "abstreet-workspace.png" });
  await page.setViewportSize({ width: 760, height: 900 });
  const smallChat = await page.locator(".traffic-chat-column").boundingBox();
  assert.ok((await dialog.boundingBox()).y >= smallChat.y + smallChat.height);
  await page.getByRole("button", { name: "收起仿真" }).click();
  await dialog.waitFor({ state: "hidden" });
  console.log("PASS: chat and simulation side by side, fullscreen, instance preservation, stacked narrow layout");
} finally {
  await browser.close();
}
