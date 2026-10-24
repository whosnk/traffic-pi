import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ channel: "msedge" });
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const cwd = process.cwd();
    const sessions = ["a", "b"].map(id => ({ id: "navigation-" + id, name: "导航测试 " + id, cwd, projectRoot: cwd, projectKey: cwd, path: cwd + "/fixture-" + id + ".jsonl", created: "2026-10-24", modified: "2026-10-24", messageCount: 1, firstMessage: "导航测试 " + id }));
    let loads = 0, polls = 0, submissions = 0;
    await page.route("**/abstreet/abstreet.html?**", route => {
      loads++;
      return route.fulfill({ contentType: "text/html", body: '<canvas width="1500" height="900"></canvas>' });
    });
    await page.route("https://tile.openstreetmap.org/**", route => route.abort());
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      let json = {};
      if (path === "/api/sessions") json = { sessions, runningSessionIds: [], sessionListVersion: 1 };
      else if (path === "/api/agent/running") json = { sessionIds: [], sessionListVersion: 1 };
      else if (/^\/api\/sessions\/navigation-[ab]$/.test(path)) {
        const id = path.split("/").at(-1);
        json = { info: sessions.find(s => s.id === id), sessionId: id, filePath: "", tree: [], leafId: null,
          context: { messages: [{ role: "user", content: "导航测试" }], entryIds: ["fixture"], hasMore: false, model: null, thinkingLevel: "off" } };
      } else if (path === "/api/models") json = { models: {}, modelList: [] };
      else if (path === "/api/project-trust") json = { trusted: true, cwd };
      else if (path === "/api/worktrees") json = { projectRoot: cwd, projectKey: cwd, worktrees: [], isGit: false };
      else if (path === "/api/home") json = { home: cwd };
      else if (path === "/api/simulation-demo") { polls++; json = { command: null }; }
      else if (path === "/api/simtrend") {
        const body = route.request().postDataJSON();
        if (body.action === "submit") submissions++;
        json = { scenarios: [], jobs: [] };
      } else if (path.startsWith("/api/agent/")) json = { state: { isStreaming: false, isPromptRunning: false }, tools: [], activeTools: [], commands: [] };
      return route.fulfill({ json });
    });
    await page.goto((process.env.E2E_BASE_URL || "http://127.0.0.1:30141") + "/?session=navigation-a");
    const workspace = page.locator("#traffic-workspace");
    const nav = page.getByRole("navigation", { name: "工作模式" });
    await page.frameLocator('iframe[title="本地交通仿真"]').locator("canvas").waitFor();
    assert.equal(await workspace.getAttribute("data-view"), "abstreet");
    assert.equal(loads, 1);
    assert.equal(await page.locator(".traffic-results-column").isVisible(), false);
    assert.equal(await page.locator(".traffic-workspace-views").count(), 0);
    for (const label of ["仿真工作台", "场景管理", "仿真实验", "分析与报告", "设置"]) {
      assert.equal(await nav.getByRole("button", { name: label, exact: true }).isVisible(), true);
    }
    if (width < 960) await workspace.getByRole("button", { name: "对话", exact: true }).click();
    await page.locator(".chat-input-textarea").fill("保留导航草稿");
    await nav.getByRole("button", { name: "场景管理", exact: true }).click();
    await page.getByRole("heading", { name: "选择交通场景" }).waitFor();
    await nav.getByRole("button", { name: "仿真实验", exact: true }).click();
    await page.locator(".simtrend-header h2").waitFor();
    assert.equal(submissions, 0);
    await nav.getByRole("button", { name: "分析与报告", exact: true }).click();
    await page.locator(".geo-toolbar").waitFor();
    await nav.getByRole("button", { name: "仿真工作台", exact: true }).click();
    assert.equal(loads, 1, "导航不得重新加载共享仿真");
    await workspace.getByRole("button", { name: "收起交通工作区" }).click();
    const previous = polls;
    await page.waitForTimeout(1300);
    assert.ok(polls > previous, "收起不得中断命令接收");
    await nav.getByRole("button", { name: "仿真工作台", exact: true }).click();
    if (width < 960 && !(await page.locator(".chat-input-textarea").isVisible())) await workspace.getByRole("button", { name: "对话", exact: true }).click();
    assert.equal(await page.locator(".chat-input-textarea").inputValue(), "保留导航草稿");
    await nav.getByRole("button", { name: "会话", exact: true }).click();
    await page.locator(".sidebar-container").getByText("导航测试 b", { exact: true }).click();
    assert.equal(loads, 1);
    await page.screenshot({ path: ".next/traffic-navigation-" + width + ".png" });
    assert.deepEqual(errors, []);
    await page.close();
    console.log("PASS: navigation " + width + "px, defaults, mounted simulation, draft/session, GIS, experiments");
  }
} finally { await browser.close(); }
