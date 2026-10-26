import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
const sessionTag = `congestion-${crypto.randomUUID()}`;
const primarySession = `${sessionTag}-a`;
const client = new Client({ name: "congestion-workspace-check", version: "1" });

const realBridge = process.env.TRAFFIC_PI_REAL_BRIDGE === "1";
const browser = await chromium.launch({ channel: "msedge" });
try {
  await client.connect(new StdioClientTransport({ command: process.execPath, args: [resolve("mcp/traffic-demo.mjs")], env: { ...process.env, TRAFFIC_PI_BASE_URL: process.env.TRAFFIC_PI_BASE_URL || "http://127.0.0.1:30141" } }));
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("dialog", dialog => dialog.accept());
  page.on("pageerror", error => pageErrors.push(error.message));
  const cwd = process.cwd();
  const sessions = ["a", "b", "empty"].map(id => ({
    id: `${sessionTag}-${id}`, name: `工作区测试 ${id}`, cwd, projectRoot: cwd, projectKey: cwd,
    path: `${cwd}/test-${id}.jsonl`, created: "2026-10-11T00:00:00Z", modified: "2026-10-11T00:00:00Z",
    messageCount: 1, firstMessage: `测试会话 ${id}`,
  }));
  const history = new Map(sessions.map(session => [session.id, [{ role: "user", content: `测试会话 ${session.id}` }]]));
  let simulationLoads = 0;
  let prompts = 0;
  let lastPrompt = "";
  await page.route("**/abstreet/abstreet.html?**", route => {
    if (route.request().method() === "HEAD") return route.continue();
    simulationLoads++;
    if (realBridge) return route.continue();
    return route.fulfill({ contentType: "text/html", body: `<canvas width="1500" height="900"></canvas><script>
    window.calls=[]; window.failAction=''; window.roads=[{roadId:37,name:'重庆长江大桥',queueVehicles:12,meanVehicleSpeedKph:4,meanVehicleDelaySeconds:33}];
    window.trafficPi={ready:true,async request(action,params){window.calls.push({action,params});if(window.failAction===action)throw new Error('测试：道路高亮失败');
    if(action==='get_road_metrics')return {roads:window.roads,simulationTime:28800};
    if(action==='get_view_state')return {width:1500,height:900,moving:false,zoom:8,nativeUi:false,anchor:params?.roadId!=null?{x:750,y:450}:null};
    return {map:'../data/system/cn/chongqing/maps/yuzhong_core.bin',randomSeed:42,scene:'weekday',paused:true,speedMultiplier:5,simulationTime:28800,capabilities:['traffic-pi-ui-v1']};}};
    </script>` });
  });
  const tile = await readFile(new URL("../public/icons/icon-192.png", import.meta.url));
  await page.route("https://tile.openstreetmap.org/**", route => route.fulfill({ contentType: "image/png", body: tile }));
  await page.addInitScript(() => {
    window.__trafficStreams = [];
    window.EventSource = class {
      readyState = 1;
      onmessage = null;
      onerror = null;
      constructor(url) {
        this.url = url;
        window.__trafficStreams.push(this);
        queueMicrotask(() => this.onmessage?.({ data: JSON.stringify({ type: "connected", isStreaming: true }) }));
      }
      close() { this.readyState = 2; }
      addEventListener() {}
      removeEventListener() {}
    };
    window.__publishTrafficEvent = (sessionId, event) => {
      const stream = window.__trafficStreams.findLast(source => source.readyState === 1 && source.url.includes(`/api/agent/${sessionId}/events`));
      if (!stream) throw new Error(`No active event stream for ${sessionId}`);
      stream.onmessage({ data: JSON.stringify(event) });
    };
  });
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.startsWith("/api/maplibre/")) return route.continue();
    if (path.startsWith("/api/files/")) return route.fulfill({ json: { type: "text", content: "# 工作区测试文件\n文件预览内容", language: "markdown", path: `${cwd}/README.md` } });
    let json = {};
    if (path === "/api/sessions") json = { sessions, runningSessionIds: [primarySession], sessionListVersion: 1 };
    else if (path === "/api/agent/running") json = { sessionIds: [primarySession], sessionListVersion: 1 };
    else if (sessions.some(session => path === `/api/sessions/${session.id}`)) {
      const id = path.split("/").at(-1);
      const messages = history.get(id);
      json = { info: sessions.find(s => s.id === id), sessionId: id, filePath: "", totalActiveMs: 0, tree: [], leafId: null,
        context: { messages, entryIds: messages.map((_, i) => `entry-${i}`), oldestEntryId: null, hasMore: false, thinkingLevel: "off", model: null } };
    } else if (path.endsWith("/state")) json = { running: path.includes(primarySession), state: { isStreaming: path.includes(primarySession), isPromptRunning: realBridge && path.includes(primarySession) } };
    else if (path === "/api/models") json = { models: {}, modelList: [] };
    else if (path === "/api/project-trust") json = { trusted: true, cwd };
    else if (path === "/api/worktrees") json = { projectRoot: cwd, projectKey: cwd, worktrees: [], isGit: false };
    else if (path === "/api/home") json = { home: cwd };
    else if (path === "/api/simulation-demo") return route.continue();
    else if (path.startsWith(`/api/agent/${sessionTag}-`) && route.request().method() === "POST") {
      const command = route.request().postDataJSON();
      if (command.type === "prompt") { prompts++; lastPrompt = command.message; }
      json = { success: true, data: ["get_tools", "get_commands"].includes(command.type) ? [] : {} };
    }
    else if (path.startsWith(`/api/agent/${sessionTag}-`)) json = { running: realBridge && path.includes(primarySession), state: { isStreaming: path.includes(primarySession), isPromptRunning: realBridge && path.includes(primarySession) }, tools: [], activeTools: [], commands: [] };
    return route.fulfill({ json });
  });
  await page.goto(`${process.env.TRAFFIC_PI_BASE_URL || "http://127.0.0.1:30141"}/?session=${primarySession}`);
  const workspace = page.getByRole("region", { name: "交通工作区", exact: true });
  await workspace.waitFor();
  await page.locator(".chat-input-textarea").waitFor();
  await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor({timeout:180000});
  assert.equal(simulationLoads, 1);

  await page.waitForFunction(sid => window.__trafficStreams.some(source => source.url.includes(`/api/agent/${sid}/events`) && source.readyState === 1), primarySession);
  const emit = event => page.evaluate(({sid, event}) => window.__publishTrafficEvent(sid, event), {sid: primarySession, event});
  const begin = async id => {
    await emit({ type: "agent_start" });
    await emit({ type: "tool_execution_start", toolCallId: id, toolName: "mcp_demo_detect_congestion_abcdef012345" });
    await page.getByRole("region", { name: "交通仿真工作台", exact: true }).waitFor();
    return client.callTool({ name: "detect_congestion", arguments: {}, _meta: { trafficPi: { sessionId: primarySession, toolCallId: id } } }, undefined, { timeout: 305000 });
  };
  const end = async (id, result) => emit({ type: "tool_execution_end", toolCallId: id, toolName: "mcp_demo_detect_congestion_abcdef012345", result, isError: !!result.isError });
  await page.locator(".chat-input-textarea").fill("保留检测前的草稿");
  let result = await begin("first-detection");
  assert.equal(result.isError, false, JSON.stringify(result));
  const firstSuccess = result;
  await end("first-detection", result);
  assert.equal(simulationLoads, 1);
  const frame = page.frames().find(frame => frame.url().includes("abstreet.html"));
  const task = page.getByRole("region", { name: "技能执行流程", exact: true });
  await task.getByText("检测完成，可在对话和分析结果中查看道路排名。", { exact: true }).waitFor();
  assert.equal(await workspace.getByRole("button", { name: /^分析结果/ }).getAttribute("aria-expanded"), "false");
  const layout = await page.evaluate(() => {
    const box = name => { const r = document.querySelector(`[aria-label="${name}"]`).getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom }; };
    return { flow: box("技能执行流程"), scene: box("场景与时间控制"), overview: box("当前任务概览"), iframe: document.querySelector('iframe[title="本地交通仿真"]').getBoundingClientRect().top };
  });
  assert.ok(layout.flow.top > layout.iframe, "Workflow must float inside the map rather than push it down");
  assert.ok(layout.flow.left >= layout.scene.right && layout.flow.right <= layout.overview.left, "Wide map controls must not overlap the workflow");
  assert.equal(await task.locator("li time[datetime]").count(), 5);
  if (realBridge) await page.screenshot({ path: ".next/congestion-workspace-floating.png" });
  await page.getByRole("button", { name: "查看分析结果", exact: true }).click();
  assert.equal(await workspace.getByRole("button", { name: /^分析结果/ }).getAttribute("aria-expanded"), "true");
  if (realBridge) {
    const detection = result.structuredContent.result;
    assert.ok(detection.roads.length > 0);
    assert.equal(detection.state.paused, true);
    assert.equal(detection.simulationTime, 28800);
    assert.equal(detection.state.speedMultiplier, 1);
    await page.getByRole("button", { name: /当前疑似拥堵道路/ }).click();
    const bubble = page.getByRole("region", { name: "道路详情", exact: true });
    await bubble.waitFor();
    await page.getByRole("button", { name: "下一处 →", exact: true }).click();
    await bubble.getByText("道路 314", { exact: true }).waitFor();
    await page.waitForTimeout(900);
    const canvas = await frame.locator("canvas").boundingBox();
    await page.mouse.move(canvas.x + canvas.width * .15, canvas.y + canvas.height * .75);
    await page.mouse.wheel(0, -120);
    await page.waitForTimeout(300);
    assert.equal(await page.getByRole("button", { name: "跟随任务", exact: true }).getAttribute("aria-pressed"), "false");
    await page.getByRole("button", { name: "全局", exact: true }).click();
    await page.waitForTimeout(900);
    await page.getByRole("button", { name: "跟随任务", exact: true }).click();
    await bubble.waitFor();
    await page.waitForTimeout(900);
    await page.getByRole("button", { name: "更多 · 原生界面", exact: true }).click();
    await page.getByRole("button", { name: "返回统一界面", exact: true }).click();
    assert.equal((await frame.evaluate(() => window.trafficPi.request("get_simulation_state"))).simulationTime, 28800);
    await page.screenshot({ path: ".next/congestion-workspace-real.png" });
    console.log("PASS: real MCP composite detection with Chongqing WASM, actual metrics, highlights, focus and completed stepper", JSON.stringify(detection.roads));
  } else {
  await page.getByRole("button", { name: /当前疑似拥堵道路/ }).click();
  await page.getByRole("button", { name: "1. 重庆长江大桥 · 定位", exact: true }).click();
  assert.equal((await frame.evaluate(() => window.calls)).at(-1).action, "focus_on_road");
  assert.equal(await page.locator(".chat-input-textarea").inputValue(), "保留检测前的草稿");
  await page.getByRole("region", { name: "道路详情", exact: true }).waitFor();
  await task.getByText(/工具详情/).click();
  await task.getByText("真实执行记录", { exact: true }).waitFor();
  await task.getByText(/工具详情/).click();
  await page.getByRole("button", { name: "更多 · 原生界面", exact: true }).click();
  await page.getByRole("button", { name: "返回统一界面", exact: true }).click();
  await page.getByRole("button", { name: "放大地图", exact: true }).click();
  await page.getByRole("button", { name: "缩小地图", exact: true }).click();
  const count = await page.locator(".traffic-result-card").count();
  await end("first-detection", result);
  assert.equal(await page.locator(".traffic-result-card").count(), count);
  result = await begin("repeat-detection"); await end("repeat-detection", result);
  assert.equal(result.isError, false, JSON.stringify(result));
  assert.equal(await workspace.getByRole("button", { name: /^分析结果/ }).getAttribute("aria-expanded"), "true", "New results must preserve an explicitly opened results panel");
  await workspace.getByRole("button", { name: "收起交通工作区", exact: true }).click();
  await frame.evaluate(() => { window.roads=[{roadId:37,queueVehicles:0,meanVehicleSpeedKph:20}];window.calls=[]; });
  result = await begin("empty-detection"); await end("empty-detection", result);
  assert.equal(result.isError, false, JSON.stringify(result));
  const calls = await frame.evaluate(() => window.calls.map(call => call.action));
  assert.ok(calls.includes("clear_highlights")); assert.ok(!calls.includes("focus_on_road"));
  await emit({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "[检测测试文件](./README.md)" }] } });
  await page.getByRole("link", { name: "检测测试文件" }).click();
  await workspace.waitFor({ state: "hidden" });
  await frame.evaluate(() => { window.roads=[{roadId:37,queueVehicles:10,meanVehicleSpeedKph:4}];window.failAction='highlight_roads'; });
  result = await begin("failed-detection"); await end("failed-detection", result);
  assert.equal(result.isError, true);
  await task.getByRole("status").filter({ hasText: /道路高亮失败/ }).waitFor();
  await task.getByRole("button", { name: "重新检测" }).click();
  await page.getByText("Agent 仍在执行或尚未准备好，请等待或停止当前任务后再开始。", { exact: true }).waitFor();
  assert.equal(prompts, 0);
  await emit({ type: "agent_end" });
  await emit({ type: "agent_settled" });
  await emit({ type: "prompt_done" });
  await task.getByRole("button", { name: "重新检测" }).click();
  await page.waitForTimeout(300);
  assert.equal(prompts, 1, "Retry must create a new Agent prompt rather than replaying a browser command");
  await frame.evaluate(() => { window.failAction='';window.trafficPi.ready=false; });
  const stopped = begin("stopped-detection");
  await page.waitForTimeout(300);
  await page.locator(".chat-input-textarea").press("Escape");
  assert.equal((await stopped).isError, true);
  await task.getByRole("status").filter({ hasText: "Agent 已停止，检测已中止。" }).waitFor();
  const resultCountBeforeLateEvent = await page.locator(".traffic-result-card").count();
  await end("stopped-detection", firstSuccess);
  assert.equal(await page.locator(".traffic-result-card").count(), resultCountBeforeLateEvent, "Stopped calls ignore late successful results");
  await emit({ type: "agent_end" });
  await emit({ type: "agent_settled" });
  await emit({ type: "prompt_done" });
  await task.getByRole("button", { name: "重新检测" }).click();
  const cancelled = begin("cancelled-detection");
  await page.waitForTimeout(300);
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "会话", exact: true }).click();
  await page.locator(".sidebar-container").getByText("工作区测试 b", { exact: true }).click();
  assert.ok(page.url().includes(primarySession), "活动检测阻止切换会话");
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "会话", exact: true }).click();
  await task.getByRole("button", { name: "取消检测", exact: true }).click();
  assert.equal((await cancelled).isError, true);
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "会话", exact: true }).click();
  await page.locator(".sidebar-container").getByText("工作区测试 b", { exact: true }).click();
  assert.equal(await page.locator(".traffic-result-card").count(), 0);
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "会话", exact: true }).click();
  await page.locator(".sidebar-container").getByText("工作区测试 a", { exact: true }).click();
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "仿真工作台", exact: true }).click();
  await task.getByRole("button", { name: "重新检测" }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "仿真工作台", exact: true }).click();
  await page.getByRole("list", { name: "执行阶段", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(350);
  const narrowLayout = await page.evaluate(() => {
    const box = name => { const r = document.querySelector(`[aria-label="${name}"]`).getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; };
    return { flow: box("技能执行流程"), scene: box("场景与时间控制"), overview: box("当前任务概览") };
  });
  assert.ok(narrowLayout.flow.bottom <= narrowLayout.scene.top && narrowLayout.flow.bottom <= narrowLayout.overview.top, "Narrow controls must sit below the workflow");
  await page.screenshot({ path: ".next/congestion-workspace-mobile.png" });
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.screenshot({ path: ".next/congestion-workspace-mobile-dark.png" });
  await page.evaluate(() => document.documentElement.classList.remove("dark"));
  assert.equal(simulationLoads, 1, "Detection preserves the existing iframe across modes and sessions");
  assert.deepEqual(pageErrors, []);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "会话", exact: true }).click();
  await page.locator(".sidebar-container").getByText("工作区测试 b", { exact: true }).click();
  await workspace.getByRole("button", { name: "收起交通工作区", exact: true }).click();
  await page.locator(".chat-input-textarea").fill("技能调用保留草稿");
  const beforeSkill = prompts;
  await page.getByRole("button", { name: "交通技能", exact: true }).click();
  await page.getByRole("complementary", { name: "专属交通技能" }).getByRole("button", { name: "开始分析", exact: true }).click();
  await page.waitForTimeout(300);
  assert.equal(prompts, beforeSkill + 1);
  assert.match(lastPrompt, /^\/skill:traffic-congestion /);
  assert.equal(await page.locator(".chat-input-textarea").inputValue(), "技能调用保留草稿");
  await page.reload();
  assert.equal(await page.locator(".traffic-result-card").count(), 0);
  await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor();
  console.log("PASS: real MCP/session routing, GIS/conversation/file auto-open, real step updates, result focus, no-match clearing, failures, retry, cancellation, drafts, lazy iframe, mobile/reduced motion, refresh");
  }
  assert.deepEqual(pageErrors, []);
} finally { await client.close(); await browser.close(); }
