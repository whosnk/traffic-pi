import assert from "node:assert/strict";
import { resolve } from "node:path";
import { chromium } from "playwright";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const client = new Client({ name: "demo-check", version: "1.0.0" });
const browser = await chromium.launch({ channel: "msedge" });
try {
  await client.connect(new StdioClientTransport({ command: process.execPath, args: [resolve("mcp/traffic-demo.mjs")] }));
  assert.ok((await client.listTools()).tools.some(tool => tool.name === "start_rush_hour_demo"));
  const forbidden = await fetch("http://127.0.0.1:30141/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json", Origin: "https://example.com" }, body: '{"action":"start"}' });
  assert.equal(forbidden.status, 403);
  const invalid = await fetch("http://127.0.0.1:30141/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: '{"action":"ack"}' });
  assert.equal(invalid.status, 409);
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  await page.goto("http://127.0.0.1:30141/?cwd=" + encodeURIComponent(process.cwd()));
  await page.getByRole("button", { name: "▧ 仿真工作台", exact: true }).click();
  await page.getByText("自动接收 MCP 演示", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "接收 MCP 演示", exact: true }).count(), 0);
  await page.waitForResponse(response => response.url().includes("/api/simulation-demo?viewer=") && response.ok());
  await page.waitForTimeout(5000);
  const result = await client.callTool({ name: "start_rush_hour_demo", arguments: {} });
  assert.equal(result.isError, false, JSON.stringify(result));
  assert.equal(JSON.parse(result.content[0].text).status, "loading");
  await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor({ timeout: 60000 });
  await page.waitForFunction(() => {
    const frame = document.querySelector('iframe[title="本地交通仿真"]');
    return frame?.contentWindow?.trafficPi?.ready === true;
  }, null, { timeout: 300000 });
  const frame = page.frames().find(item => item.url().includes("cn/chongqing/scenarios/yuzhong_core/weekday.bin") && item.url().includes("--time=08:00:00"));
  assert.ok(frame, "MCP must start the Chongqing rush-hour scene in the embedded frame");
  const canvas = frame.locator("canvas");
  const first = await canvas.screenshot({ path: ".next/traffic-demo-before.png" });
  const advanced = await client.callTool({ name: "run_for", arguments: { durationSeconds: 1 } });
  assert.equal(advanced.isError, false, JSON.stringify(advanced));
  assert.ok(JSON.parse(advanced.content[0].text).simulationTime > 28800);
  const second = await canvas.screenshot({ path: ".next/traffic-demo-after.png" });
  assert.ok(!first.equals(second), "Advancing the simulation must change the canvas");
  console.log("PASS: real MCP discovery/call, browser acknowledgment, controlled rush-hour advance, cross-origin rejection, invalid acknowledgment");
  console.log(JSON.stringify(result));
} finally {
  await client.close();
  await browser.close();
}
