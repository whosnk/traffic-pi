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
  await page.route("**/abstreet/abstreet.html?**", route => {
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
    if (path === "/api/sessions") json = { sessions, runningSessionIds: ["workspace-a"], sessionListVersion: 1 };
    else if (path === "/api/agent/running") json = { sessionIds: ["workspace-a"], sessionListVersion: 1 };
    else if (/^\/api\/sessions\/workspace-[^/]+$/.test(path)) {
      const id = path.split("/").at(-1);
      const messages = history.get(id);
      json = { info: sessions.find(s => s.id === id), sessionId: id, filePath: "", totalActiveMs: 0, tree: [], leafId: null,
        context: { messages, entryIds: messages.map((_, i) => `entry-${i}`), oldestEntryId: null, hasMore: false, thinkingLevel: "off", model: null } };
    } else if (path.endsWith("/state")) json = { running: path.includes("workspace-a"), state: { isStreaming: path.includes("workspace-a"), isPromptRunning: false } };
    else if (path === "/api/models") json = { models: {}, modelList: [] };
    else if (path === "/api/project-trust") json = { trusted: true, cwd };
    else if (path === "/api/worktrees") json = { projectRoot: cwd, projectKey: cwd, worktrees: [], isGit: false };
    else if (path === "/api/home") json = { home: cwd };
    else if (path === "/api/simulation-demo") { polls++; json = { command: null }; }
    else if (path.startsWith("/api/agent/workspace-")) json = { state: { isStreaming: path.includes("workspace-a"), isPromptRunning: false }, tools: [], activeTools: [], commands: [] };
    return route.fulfill({ json });
  });
  await page.goto("http://127.0.0.1:30141/?session=workspace-a");
  const workspace = page.getByRole("region", { name: "交通工作区", exact: true });
  await workspace.waitFor();
  await page.locator(".chat-input-textarea").waitFor();
  await page.locator(".geo-map canvas").waitFor();
  assert.equal(simulationLoads, 0);
  assert.equal(polls, 0);
  await page.waitForFunction(() => window.__trafficStreams.some(source => source.url.includes("workspace-a") && source.readyState === 1));
  const publish = async value => {
    const message = toolMessage(value);
    history.get("workspace-a").push(message);
    await page.evaluate(message => window.__publishTrafficEvent("workspace-a", { type: "message_end", message }), message);
  };
  await page.locator(".chat-input-textarea").fill("保留这段交通方案草稿");
  const chatScroll = page.locator(".traffic-chat-column .overflow-y-auto").first();
  const scrollPosition = await chatScroll.evaluate(element => {
    element.scrollTop = (element.scrollHeight - element.clientHeight) / 2;
    return element.scrollTop;
  });
  assert.ok(scrollPosition > 0);
  await page.getByRole("button", { name: "仿真 · 方案验证" }).click();
  await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor();
  assert.equal(await chatScroll.evaluate(element => element.scrollTop), scrollPosition, "Switching tools must preserve the chat scroll position");
  const frame = page.frames().find(item => item.url().includes("abstreet.html"));
  await publish(scene(1));
  await page.locator(".traffic-result-notice").waitFor();
  assert.equal(await workspace.getAttribute("data-view"), "simulation", "New results must not switch tools");
  await workspace.getByRole("button", { name: "查看结果", exact: true }).click();
  await page.locator(".traffic-result-notice").waitFor({ state: "hidden" });
  await page.getByRole("checkbox", { name: "测试道路 A", exact: true }).waitFor();
  await page.waitForTimeout(750);
  const canvas = page.locator(".geo-map canvas");
  const mapNode = await canvas.elementHandle();
  const beforeUpdate = await canvas.screenshot({ path: ".next/gis-before-update.png" });
  await publish({ ...scene(2), center: [107.55, 30.56] });
  await page.locator(".geo-toolbar").getByText("rev 2", { exact: true }).waitFor();
  await page.waitForTimeout(300);
  assert.ok(beforeUpdate.equals(await canvas.screenshot({ path: ".next/gis-after-update.png" })), "Updating a visible scene must preserve the camera");
  await workspace.getByRole("button", { name: "查看结果", exact: true }).click();
  await publish(scene(1));
  await page.waitForTimeout(200);
  assert.equal(await page.locator(".traffic-result-notice").count(), 0, "Old revisions must not raise unread notices");
  const layer = page.getByRole("checkbox", { name: "测试道路 A", exact: true });
  await layer.uncheck();
  await page.getByRole("button", { name: "仿真 · 方案验证" }).click();
  const pollCount = polls;
  await page.getByRole("button", { name: /GIS · 路网观察/ }).click();
  await page.waitForTimeout(1200);
  assert.ok(polls > pollCount, "A started simulation keeps receiving commands in GIS");
  assert.equal(await layer.isChecked(), false);
  assert.ok(await mapNode.evaluate(element => element.isConnected));
  await page.getByRole("button", { name: "收起交通工作区" }).click();
  await workspace.waitFor({ state: "hidden" });
  await page.waitForTimeout(200);
  const stoppedPolls = polls;
  await page.waitForTimeout(1200);
  assert.equal(polls, stoppedPolls, "Closing the workspace must stop polling");
  await publish(scene(3));
  await page.locator(".traffic-result-notice").getByRole("button", { name: "查看结果" }).click();
  await workspace.waitFor();
  assert.equal(await layer.isChecked(), false);
  assert.equal(await page.locator(".chat-input-textarea").inputValue(), "保留这段交通方案草稿");
  const selectSession = async name => {
    await page.getByRole("button", { name: /Show sidebar|显示侧边栏/ }).click();
    await page.locator(".sidebar-container").getByText(name, { exact: true }).click();
    await page.getByRole("button", { name: "交通工作区", exact: true }).click();
  };
  await selectSession("工作区测试 b");
  await page.getByRole("checkbox", { name: "测试道路 B", exact: true }).waitFor();
  assert.equal(await page.getByRole("checkbox", { name: "测试道路 B", exact: true }).isChecked(), true);
  await selectSession("工作区测试 empty");
  await page.locator(".geo-toolbar").getByText("暂无分析图层", { exact: true }).waitFor();
  assert.equal(await page.locator(".geo-layers input").count(), 0);
  assert.equal(await page.locator(".traffic-result-notice").count(), 0);
  await selectSession("工作区测试 a");
  await page.locator(".geo-toolbar").getByText("rev 3", { exact: true }).waitFor();
  assert.equal(await page.locator(".traffic-result-notice").count(), 0, "Seen results remain seen after switching sessions");
  assert.equal(page.frames().find(item => item.url().includes("abstreet.html")), frame);
  assert.equal(simulationLoads, 1);
  await page.evaluate(() => window.__publishTrafficEvent("workspace-a", { type: "message_end", message: {
    role: "assistant", model: "fixture", provider: "fixture", content: [{ type: "text", text: "[工作区测试文件](./README.md)" }],
  } }));
  await page.getByRole("link", { name: "工作区测试文件" }).click();
  await workspace.waitFor({ state: "hidden" });
  assert.equal(await page.locator("#file-panel").getAttribute("class").then(value => value.includes("right-panel-open")), true);
  await page.getByRole("button", { name: "交通工作区", exact: true }).click();
  await workspace.waitFor();
  await page.getByRole("button", { name: "仿真 · 方案验证" }).focus();
  await page.keyboard.press("Enter");
  assert.equal(await workspace.getAttribute("data-view"), "simulation");
  await page.getByRole("button", { name: /GIS · 路网观察/ }).focus();
  await page.keyboard.press("Enter");
  assert.equal(await workspace.getAttribute("data-view"), "gis");
  await page.screenshot({ path: ".next/traffic-workspace-gis.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(350);
  const chat = await page.locator(".traffic-chat-column").boundingBox();
  assert.ok((await workspace.boundingBox()).y >= chat.y + chat.height);
  await page.screenshot({ path: ".next/traffic-workspace-mobile.png" });
  await page.route("https://tile.openstreetmap.org/**", route => route.abort());
  await page.reload();
  await page.locator(".geo-error").waitFor();
  assert.equal(await page.locator('iframe[title="本地交通仿真"]').count(), 0);
  await page.getByRole("button", { name: "仿真 · 方案验证" }).click();
  await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor();
  assert.deepEqual(pageErrors, []);
  console.log("PASS: SSE result routing, explicit result navigation, camera/layer preservation, unread/session isolation, lazy iframe, polling lifecycle, file panel exclusivity");
} finally {
  await browser.close();
}
