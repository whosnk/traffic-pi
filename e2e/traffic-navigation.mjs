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
    let loads = 0, polls = 0, submissions = 0, jobPolls = 0;
    let agentBusy = false, unavailable = false;
    const scenarios = [{ scenario_id: "four_intersections", name: "四交叉口路网", description: "后端四交叉口", intersections: [], supported_capabilities: ["查询", "实验"] }, { scenario_id: "nanjing_south_ride_hailing", name: "南京南站网约车停车管理", description: "后端南京南站", intersections: [], supported_capabilities: ["网约车实验"] }];
    await page.route("**/abstreet/abstreet.html?**", route => {
      loads++;
      return route.fulfill({ contentType: "text/html", body: '<canvas width="1500" height="900"></canvas>' });
    });
    await page.route("https://tile.openstreetmap.org/**", route => route.abort());
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path.startsWith("/api/maplibre/")) return route.continue();
      let json = {};
      if (path === "/api/sessions") json = { sessions, runningSessionIds: agentBusy ? ["navigation-a"] : [], sessionListVersion: 1 };
      else if (path === "/api/agent/running") json = { runningSessionIds: agentBusy ? ["navigation-a"] : [], sessionListVersion: 1 };
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
        if (body.action === "start") submissions++;
        if (body.action === "scenarios" && unavailable) return route.fulfill({ status: 500, json: { ok: false, message: "测试连接不可用" } });
        const job = { id: "persisted-four", title: "已有任务", tool: "fixture", arguments: { scenario_id: "four_intersections" }, status: "running", steps: [], artifacts: [], created_at: "2026-10-24" };
        if (body.action === "scenarios") json = { scenarios };
        else if (body.action === "map") json = { scenario_id: body.scenario_id, name: body.scenario_id, synthetic: true, center: [0,0], zoom: 12, edges: [], lanes: {}, zones: [] };
        else if (body.action === "jobs") json = { jobs: [job] };
        else if (body.action === "job") { jobPolls++; json = { job }; }
      } else if (path.endsWith("/state")) json = { running: agentBusy, state: { isStreaming: agentBusy, isPromptRunning: agentBusy } };
      else if (path.startsWith("/api/agent/")) json = { state: { isStreaming: agentBusy, isPromptRunning: agentBusy }, tools: [], activeTools: [], commands: [] };
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
    const fourCard = page.locator(".traffic-scenario-grid article").filter({ hasText: "四交叉口路网" });
    const highway = page.locator(".traffic-scenario-grid article").filter({ hasText: "高速公路场景" });
    await fourCard.waitFor();
    assert.equal(await highway.getByRole("button").isDisabled(), true);
    assert.match(await fourCard.innerText(), /SUMO.*空间对象与实验结果回放/s);
    await fourCard.getByRole("button", { name: "打开实验场景" }).click();
    const experiment = page.locator(".simtrend-scene-workspace:not([hidden])");
    await experiment.getByRole("button", { name: "创建仿真任务", exact: true }).click();
    await experiment.getByLabel("事件类型").selectOption("追尾事故");
    await experiment.getByLabel("持续时间（分钟）").fill("17");
    const pollsBeforeSwitch = jobPolls;
    await page.getByLabel("仿真场景").selectOption("nanjing_south_ride_hailing");
    await experiment.getByRole("button", { name: "创建仿真任务", exact: true }).click();
    assert.equal(await experiment.getByLabel("事件类型").inputValue(), "");
    await experiment.getByLabel("任务类型").selectOption("demand");
    await experiment.getByLabel("调整幅度（%）").fill("27");
    await page.getByLabel("仿真场景").selectOption("four_intersections");
    assert.equal(await experiment.getByLabel("持续时间（分钟）").inputValue(), "17");
    assert.equal(await experiment.getByLabel("事件类型").inputValue(), "追尾事故");
    await page.waitForTimeout(1700);
    assert.ok(jobPolls > pollsBeforeSwitch, "后台持久化任务仍在轮询");
    await page.getByLabel("仿真场景").selectOption("nanjing_south_ride_hailing");
    assert.equal(await experiment.getByLabel("调整幅度（%）").inputValue(), "27");
    await nav.getByRole("button", { name: "场景管理", exact: true }).click();
    unavailable = true;
    await page.getByRole("button", { name: "刷新场景列表", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "测试连接不可用" }).waitFor();
    assert.equal(await page.locator(".traffic-scenario-grid article").count(), 2);
    unavailable = false;
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
    await nav.getByRole("button", { name: "场景管理", exact: true }).click();
    await fourCard.waitFor();
    await page.screenshot({ path: ".next/traffic-navigation-" + width + ".png" });
    agentBusy = true;
    await page.goto((process.env.E2E_BASE_URL || "http://127.0.0.1:30141") + "/?session=navigation-a");
    await nav.getByRole("button", { name: "场景管理", exact: true }).click();
    await fourCard.waitFor();
    await page.getByRole("status").filter({ hasText: "Agent 正在执行" }).waitFor();
    assert.equal(await fourCard.getByRole("button").isDisabled(), true);
    assert.equal(submissions, 0);
    assert.deepEqual(errors, []);
    await page.close();
    console.log("PASS: navigation " + width + "px, defaults, mounted simulation, draft/session, GIS, experiments");
  }
} finally { await browser.close(); }
