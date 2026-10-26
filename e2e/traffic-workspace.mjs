import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const browser = await chromium.launch({ channel: "msedge" });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const cwd = process.cwd();
  const sessions = ["a", "b", "empty"].map(id => ({
    id: `workspace-${id}`, name: `工作区测试 ${id}`, cwd, projectRoot: cwd, projectKey: cwd,
    path: `${cwd}/test-${id}.jsonl`, created: "2026-10-11T00:00:00Z", modified: "2026-10-11T00:00:00Z",
    messageCount: 1, firstMessage: `测试会话 ${id}`,
  }));
  const scene = (revision, title = "测试道路 A") => ({
    type: "traffic-pi-geo", revision, title, center: [106.55, 29.56], zoom: 12,
    sources: [{ id: "roads", data: { type: "FeatureCollection", features: [
      { type: "Feature", id: "road-1", properties: {}, geometry: { type: "LineString", coordinates: [[106.54, 29.55], [106.56, 29.57]] } },
    ] } }],
    layers: [{ id: "road-metrics", sourceId: "roads", type: "line", title, color: "#dc2626", width: 8 }],
  });
  const history = new Map(sessions.map(s => [s.id, [{ role: "user", content: `测试会话 ${s.id}` }]]));
  history.get("workspace-a").unshift(...Array.from({ length: 24 }, (_, index) => ({ role: "user", content: `路段 ${index}：核对高峰时段车流与道路通行能力。`.repeat(8) })));
  const toolMessage = value => ({ role: "toolResult", toolCallId: `geo-${value.revision}`, toolName: "publish_geo_scene", content: [{ type: "text", text: JSON.stringify(value) }] });
  history.get("workspace-b").push(toolMessage(scene(1, "测试道路 B")));
  let simulationLoads = 0;
  let polls = 0;
  let agentBusy = true;
  await page.route("**/abstreet/abstreet.html?**", route => {
    if (route.request().method() === "HEAD") return route.continue();
    simulationLoads++;
    return route.fulfill({ contentType: "text/html", body: '<canvas width="1500" height="900"></canvas>' });
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
      const stream = window.__trafficStreams.findLast(source => source.readyState === 1 && source.url.includes(sessionId));
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
    if (path === "/api/sessions") json = { sessions, runningSessionIds: agentBusy ? ["workspace-a"] : [], sessionListVersion: 1 };
    else if (path === "/api/agent/running") json = { sessionIds: agentBusy ? ["workspace-a"] : [], sessionListVersion: 1 };
    else if (/^\/api\/sessions\/workspace-[^/]+$/.test(path)) {
      const id = path.split("/").at(-1);
      const messages = history.get(id);
      json = { info: sessions.find(s => s.id === id), sessionId: id, filePath: "", totalActiveMs: 0, tree: [], leafId: null,
        context: { messages, entryIds: messages.map((_, i) => `entry-${i}`), oldestEntryId: null, hasMore: false, thinkingLevel: "off", model: null } };
    } else if (path.endsWith("/state")) json = { running: agentBusy && path.includes("workspace-a"), state: { isStreaming: agentBusy && path.includes("workspace-a"), isPromptRunning: false } };
    else if (path === "/api/models") json = { models: {}, modelList: [] };
    else if (path === "/api/project-trust") json = { trusted: true, cwd };
    else if (path === "/api/worktrees") json = { projectRoot: cwd, projectKey: cwd, worktrees: [], isGit: false };
    else if (path === "/api/home") json = { home: cwd };
    else if (path === "/api/simulation-demo") { polls++; json = { command: null }; }
    else if (path === "/api/simtrend") json = { scenarios: [], jobs: [] };
    else if (path.startsWith("/api/agent/workspace-")) json = { state: { isStreaming: agentBusy && path.includes("workspace-a"), isPromptRunning: false }, tools: [], activeTools: [], commands: [] };
    return route.fulfill({ json });
  });
  await page.goto((process.env.E2E_BASE_URL || "http://127.0.0.1:30141") + "/?session=workspace-a");
  const workspace = page.getByRole("region", { name: "交通工作区", exact: true });
  await workspace.waitFor();
  await page.locator(".chat-input-textarea").waitFor();
  await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor();
  assert.equal(simulationLoads, 1);
  await page.waitForFunction(() => window.__trafficStreams.some(source => source.url.includes("workspace-a") && source.readyState === 1));
  const publish = async value => {
    const message = toolMessage(value);
    history.get("workspace-a").push(message);
    await page.evaluate(message => {
      window.__publishTrafficEvent("workspace-a", { type: "agent_start" });
      window.__publishTrafficEvent("workspace-a", { type: "message_end", message });
      for (const type of ["agent_end", "agent_settled", "prompt_done"]) window.__publishTrafficEvent("workspace-a", { type });
    }, message);
  };
  await page.locator(".chat-input-textarea").fill("保留这段交通方案草稿");
  const modes = page.getByRole("navigation", { name: "工作模式" });
  const results = page.getByRole("complementary", { name: "分析结果", exact: true });
  assert.equal(await results.locator(".traffic-result-card").count(), 0, "Historical chat must not populate the temporary rail");
  const skillEntry = modes.getByRole("button", { name: "交通技能", exact: true });
  await skillEntry.click();
  const skills = page.getByRole("complementary", { name: "专属交通技能" });
  await skills.waitFor();
  const skillCard = skills.getByRole("button", { name: /仿真控制/ });
  await skillCard.hover();
  await skills.getByText("确认已连接工具、路网和需求", { exact: true }).waitFor();
  await skillCard.click();
  await skillCard.focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.locator(".chat-input-textarea").inputValue(), "保留这段交通方案草稿", "Skill cards must not change the draft");
  await page.keyboard.press("Escape");
  await skills.waitFor({ state: "hidden" });
  assert.equal(await skillEntry.evaluate(element => element === document.activeElement), true);
  await workspace.getByRole("button", { name: "收起交通工作区" }).click();
  await workspace.waitFor({ state: "hidden" });
  agentBusy = false;
  await page.evaluate(() => { for (const type of ["agent_end", "agent_settled", "prompt_done"]) window.__publishTrafficEvent("workspace-a", { type }); });
  await page.waitForTimeout(2700);
  await modes.getByRole("button", { name: "仿真实验" }).click();
  await workspace.getByRole("heading", { name: "仿真实验 · SUMO" }).waitFor();
  assert.equal(simulationLoads, 1, "实验导航复用原有主地图");
  await modes.getByRole("button", { name: "分析与报告", exact: true }).click();
  const chatScroll = page.locator(".traffic-chat-column .overflow-y-auto").first();
  const scrollPosition = await chatScroll.evaluate(element => {
    element.scrollTop = (element.scrollHeight - element.clientHeight) / 2;
    return element.scrollTop;
  });
  assert.ok(scrollPosition > 0);
  await modes.getByRole("button", { name: "仿真工作台", exact: true }).click();
  await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor();
  assert.equal(await chatScroll.evaluate(element => element.scrollTop), scrollPosition, "Switching tools must preserve the chat scroll position");
  const frame = page.frames().find(item => item.url().includes("abstreet.html"));
  await publish(scene(1));
  await page.locator(".traffic-result-notice").waitFor();
  assert.equal(await workspace.getAttribute("data-view"), "abstreet", "New results must not switch tools");
  await workspace.getByRole("button", { name: "查看结果", exact: true }).click();
  await page.locator(".traffic-result-notice").waitFor({ state: "hidden" });
  await page.getByRole("checkbox", { name: "测试道路 A", exact: true }).waitFor();
  await page.waitForTimeout(750);
  const canvas = page.locator(".geo-map canvas");
  const mapNode = await canvas.elementHandle();
  // Keep the unread banner from resizing the canvas during the camera-only check.
  const cameraStyle = await page.addStyleTag({ content: ".traffic-history-notice { display: none !important; }" });
  await page.waitForTimeout(300);
  const beforeUpdate = await canvas.screenshot({ path: ".next/gis-before-update.png" });
  await publish({ ...scene(2), center: [107.55, 30.56] });
  await page.locator(".geo-toolbar").getByText("rev 2", { exact: true }).waitFor();
  await page.waitForTimeout(300);
  assert.ok(beforeUpdate.equals(await canvas.screenshot({ path: ".next/gis-after-update.png" })), "Updating a visible scene must preserve the camera");
  await cameraStyle.evaluate(element => element.remove());
  await workspace.getByRole("button", { name: "查看结果", exact: true }).click();
  await publish(scene(1));
  await page.waitForTimeout(200);
  assert.equal(await page.locator(".traffic-result-notice").count(), 0, "Old revisions must not raise unread notices");
  assert.equal(await results.locator(".traffic-result-card").count(), 2, "Duplicate or old results must not create cards");
  const layer = page.getByRole("checkbox", { name: "测试道路 A", exact: true });
  await layer.uncheck();
  await modes.getByRole("button", { name: "仿真工作台", exact: true }).click();
  const pollCount = polls;
  await modes.getByRole("button", { name: "分析与报告", exact: true }).click();
  await page.waitForTimeout(1200);
  assert.ok(polls > pollCount, "A started simulation keeps receiving commands in GIS");
  assert.equal(await layer.isChecked(), false);
  assert.ok(await mapNode.evaluate(element => element.isConnected));
  await page.getByRole("button", { name: "收起交通工作区" }).click();
  await workspace.waitFor({ state: "hidden" });
  await page.waitForTimeout(200);
  const stoppedPolls = polls;
  await page.waitForTimeout(1200);
  assert.ok(polls > stoppedPolls, "Closing the workspace preserves command reception");
  await publish(scene(3));
  await page.locator(".traffic-result-notice").getByRole("button", { name: "查看结果" }).click();
  await workspace.waitFor();
  assert.equal(await layer.isChecked(), false);
  assert.equal(await page.locator(".chat-input-textarea").inputValue(), "保留这段交通方案草稿");
  const selectSession = async name => {
    if (name === "工作区测试 a") agentBusy = true;
    await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "会话", exact: true }).click();
    await page.locator(".sidebar-container").getByText(name, { exact: true }).click();
    await modes.getByRole("button", { name: "分析与报告", exact: true }).click();
  };
  await selectSession("工作区测试 b");
  assert.equal(await results.locator(".traffic-result-card").count(), 0);
  await page.getByRole("checkbox", { name: "测试道路 B", exact: true }).waitFor();
  assert.equal(await page.getByRole("checkbox", { name: "测试道路 B", exact: true }).isChecked(), true);
  await selectSession("工作区测试 empty");
  await page.locator(".geo-toolbar").getByText("暂无分析图层", { exact: true }).waitFor();
  assert.equal(await page.locator(".geo-layers input").count(), 0);
  assert.equal(await page.locator(".traffic-result-notice").count(), 0);
  await selectSession("工作区测试 a");
  await page.waitForFunction(() => window.__trafficStreams.some(source => source.url.includes("workspace-a") && source.readyState === 1));
  await page.locator(".geo-toolbar").getByText("rev 3", { exact: true }).waitFor();
  assert.equal(await page.locator(".traffic-result-notice").count(), 0, "Seen results remain seen after switching sessions");
  assert.equal(page.frames().find(item => item.url().includes("abstreet.html")), frame);
  assert.equal(simulationLoads, 1);
  assert.equal(await results.locator(".traffic-result-card").count(), 3, "Returning to a session restores its temporary results");
  await results.locator(".traffic-result-card").last().getByRole("button").click();
  await page.locator(".geo-toolbar").getByText("rev 1", { exact: true }).waitFor();
  await publish(scene(4));
  assert.equal(await page.locator(".geo-toolbar").getByText("rev 1", { exact: true }).count(), 1, "New scenes must not interrupt historical viewing");
  await workspace.getByRole("button", { name: "返回最新结果", exact: true }).click();
  await page.locator(".geo-toolbar").getByText("rev 4", { exact: true }).waitFor();
  const metricMessage = { role: "toolResult", toolCallId: "road-metric", toolName: "mcp_demo_get_road_metrics_abcdef012345", content: [{ type: "text", text: JSON.stringify({ structuredContent: { status: "completed", simulationTime: 28800, result: { roads: [{ roadId: 1, speedKph: 23, queue: null }], units: { speedKph: "km/h" } } } }) }] };
  await page.evaluate(() => window.__publishTrafficEvent("workspace-a", { type: "agent_start" }));
  await page.evaluate(message => window.__publishTrafficEvent("workspace-a", { type: "tool_execution_end", toolCallId: message.toolCallId, toolName: message.toolName, result: { content: message.content } }), metricMessage);
  await page.evaluate(message => window.__publishTrafficEvent("workspace-a", { type: "message_end", message }), metricMessage);
  await results.getByRole("button", { name: /道路指标/ }).click();
  await results.getByText("speedKph", { exact: true }).first().waitFor();
  await results.getByText("未提供", { exact: true }).waitFor();
  assert.equal(await results.locator(".traffic-result-card").count(), 5, "Tool completion and message completion must be deduplicated");
  assert.equal(await workspace.getAttribute("data-view"), "gis", "Viewing metrics must not switch or rewind simulation");
  agentBusy = false;
  await page.evaluate(() => { for (const type of ["agent_end", "agent_settled", "prompt_done"]) window.__publishTrafficEvent("workspace-a", { type }); });
  await page.waitForTimeout(2700);
  await modes.getByRole("button", { name: "仿真实验" }).click();
  await modes.getByRole("button", { name: "分析与报告", exact: true }).click();
  const beforeCollapse = await chatScroll.evaluate(element => element.scrollTop);
  await workspace.getByRole("button", { name: "对话", exact: true }).click();
  assert.equal(await page.locator(".traffic-chat-column").isVisible(), false);
  await workspace.getByRole("button", { name: "对话", exact: true }).click();
  assert.equal(await page.locator(".chat-input-textarea").inputValue(), "保留这段交通方案草稿");
  assert.equal(await chatScroll.evaluate(element => element.scrollTop), beforeCollapse, "Collapsing chat must preserve its scroll position");
  const fileMessage = { role: "assistant", model: "fixture", provider: "fixture", content: [{ type: "text", text: "[工作区测试文件](./README.md)" }] };
  history.get("workspace-a").push(fileMessage);
  await page.evaluate(message => {
    window.__publishTrafficEvent("workspace-a", { type: "agent_start" });
    window.__publishTrafficEvent("workspace-a", { type: "message_end", message });
    for (const type of ["agent_end", "agent_settled", "prompt_done"]) window.__publishTrafficEvent("workspace-a", { type });
  }, fileMessage);
  await page.getByRole("link", { name: "工作区测试文件" }).click();
  await workspace.waitFor({ state: "hidden" });
  assert.equal(await page.locator("#file-panel").getAttribute("class").then(value => value.includes("right-panel-open")), true);
  await page.getByRole("button", { name: "交通工作区", exact: true }).click();
  await workspace.waitFor();
  await modes.getByRole("button", { name: "仿真工作台", exact: true }).focus();
  await page.keyboard.press("Enter");
  assert.equal(await workspace.getAttribute("data-view"), "abstreet");
  await modes.getByRole("button", { name: "分析与报告", exact: true }).focus();
  await page.keyboard.press("Enter");
  assert.equal(await workspace.getAttribute("data-view"), "gis");
  await page.screenshot({ path: ".next/traffic-workspace-gis.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(350);
  assert.equal(await page.locator(".traffic-chat-column").isVisible(), false);
  await workspace.getByRole("button", { name: "对话", exact: true }).click();
  assert.equal(await page.locator(".traffic-chat-column").isVisible(), true);
  await modes.getByRole("button", { name: "结果面板", exact: true }).click();
  assert.equal(await page.locator(".traffic-chat-column").isVisible(), false);
  assert.equal(await results.isVisible(), true);
  await page.getByRole("button", { name: "收起分析结果" }).click();
  await skillEntry.click();
  await skills.getByRole("button", { name: /信号配时分析/ }).click();
  await skills.getByText("读取路口、周期、相位和时间窗", { exact: true }).waitFor();
  await skills.getByRole("button", { name: "关闭交通技能", exact: true }).click();
  await page.screenshot({ path: ".next/traffic-workspace-mobile.png" });
  await page.route("https://tile.openstreetmap.org/**", route => route.abort());
  await page.reload();
  assert.equal(await page.locator(".traffic-result-card").count(), 0, "Refreshing must clear temporary results even when history contains scenes");
  await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor();
  await modes.getByRole("button", { name: "分析与报告", exact: true }).click();
  await page.locator(".geo-error").waitFor();
  await modes.getByRole("button", { name: "仿真工作台", exact: true }).click();
  await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor();
  assert.deepEqual(pageErrors, []);
  console.log("PASS: four modes, display-only skills, historical GIS and metric results, deduplication, refresh/session isolation, draft/scroll/camera preservation, lazy iframe, polling, file preview, keyboard and narrow panels");
} finally {
  await browser.close();
}
