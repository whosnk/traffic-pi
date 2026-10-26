import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { resolve } from "node:path";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
const sessionTag = `congestion-${crypto.randomUUID()}`;
const primarySession = `${sessionTag}-a`;
const client = new Client({ name: "congestion-workspace-check", version: "1" });

const browser = await chromium.launch({ channel: "msedge" });
try {
  await client.connect(new StdioClientTransport({ command: process.execPath, args: [resolve("mcp/traffic-demo.mjs")], env: { ...process.env, TRAFFIC_PI_BASE_URL: process.env.TRAFFIC_PI_BASE_URL || "http://127.0.0.1:30141" } }));
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(30000);
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const cwd = process.cwd();
  const sessions = ["a", "b", "empty"].map(id => ({
    id: `${sessionTag}-${id}`, name: `工作区测试 ${id}`, cwd, projectRoot: cwd, projectKey: cwd,
    path: `${cwd}/test-${id}.jsonl`, created: "2026-10-11T00:00:00Z", modified: "2026-10-11T00:00:00Z",
    messageCount: 1, firstMessage: `测试会话 ${id}`,
  }));
  const history = new Map(sessions.map(session => [session.id, [{ role: "user", content: `测试会话 ${session.id}` }]]));
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
    } else if (path.endsWith("/state")) json = { running: path.includes(primarySession), state: { isStreaming: path.includes(primarySession), isPromptRunning: false } };
    else if (path === "/api/models") json = { models: {}, modelList: [] };
    else if (path === "/api/project-trust") json = { trusted: true, cwd };
    else if (path === "/api/worktrees") json = { projectRoot: cwd, projectKey: cwd, worktrees: [], isGit: false };
    else if (path === "/api/home") json = { home: cwd };
    else if (path === "/api/simulation-demo") return route.continue();
    else if (path.startsWith(`/api/agent/${sessionTag}-`) && route.request().method() === "POST") {
      const command = route.request().postDataJSON();
      json = { success: true, data: ["get_tools", "get_commands"].includes(command.type) ? [] : {} };
    }
    else if (path.startsWith(`/api/agent/${sessionTag}-`)) json = { state: { isStreaming: path.includes(primarySession), isPromptRunning: false }, tools: [], activeTools: [], commands: [] };
    return route.fulfill({ json });
  });
  await page.goto(`${process.env.TRAFFIC_PI_BASE_URL || "http://127.0.0.1:30141"}/?session=${primarySession}`);
  await page.getByRole("region",{name:"交通工作区",exact:true}).waitFor();
  await page.locator(".chat-input-textarea").fill("缓解分析保留草稿");
  await page.waitForFunction(sid=>window.__trafficStreams.some(s=>s.url.includes(`/api/agent/${sid}/events`)&&s.readyState===1),primarySession);
  const emit=event=>page.evaluate(({sid,event})=>window.__publishTrafficEvent(sid,event),{sid:primarySession,event});
  const run=async(name,id,args={})=>{
    await emit({type:"agent_start"});
    await emit({type:"tool_execution_start",toolCallId:id,toolName:`mcp_demo_${name}_abcdef012345`});
    const result=await client.callTool({name,arguments:args,_meta:{trafficPi:{sessionId:primarySession,toolCallId:id}}},undefined,{timeout:305000});
    await emit({type:"tool_execution_end",toolCallId:id,toolName:`mcp_demo_${name}_abcdef012345`,result,isError:!!result.isError});
    await emit({type:"agent_end"});await emit({type:"agent_settled"});await emit({type:"prompt_done"});
    assert.equal(result.isError,false,JSON.stringify(result));
    return result;
  };

  await page.waitForFunction(()=>document.querySelector('iframe[title="本地交通仿真"]')?.contentWindow?.trafficPi?.ready,null,{timeout:180000});
  const frame=page.frames().find(f=>f.url().includes("abstreet.html"));
  const request=(action,params={})=>frame.evaluate(({action,params})=>window.trafficPi.request(action,params),{action,params});
  const {intersections}=await request("get_intersection_metrics");
  const intersectionId=intersections[0].intersectionId;
  const original=await request("get_signal_plan",{intersectionId});
  // Fixed timing exists only in this isolated test window; the shipped city is unchanged.
  await request("apply_signal_plan",{intersectionId,stageDurationsSeconds:original.stages.map(stage=>Math.max(stage.durationSeconds,stage.minimumSeconds))});
  const roadId=original.stages.flatMap(stage=>stage.movements).find(movement=>!movement.crosswalk).fromRoadId;
  const analysis=run("analyze_congestion_cause","real-signal-ui",{roadId}).then(value=>value,error=>error);
  const panel=page.getByRole("region",{name:"拥堵缓解方案",exact:true});
  await panel.getByRole("button",{name:"暂停观察",exact:true}).click();
  await page.getByRole("region",{name:"技能执行流程",exact:true}).getByRole("status").filter({hasText:/已暂停观察/}).waitFor();
  await panel.getByRole("status").filter({hasText:/相位.*剩余/}).waitFor();
  await request("focus_on_intersection",{intersectionId,zoom:10,smooth:false,padding:{top:210,bottom:80,left:30,right:290}});
  for(const [width,height] of [[1719,889],[1440,900],[1280,720]]){
    await page.setViewportSize({width,height});await page.waitForTimeout(500);
    await page.screenshot({path:`.next/signal-visual/real-workspace-${width}.png`});
    const controls=await panel.getByRole("button",{name:"继续验证",exact:true}).boundingBox();
    assert.ok(controls && controls.y+controls.height<=height);
  }
  await panel.getByRole("button",{name:"取消任务并恢复",exact:true}).click();
  await analysis;
  await page.getByRole("region",{name:"技能执行流程",exact:true}).getByRole("status").filter({hasText:/任务已取消/}).waitFor();
  assert.equal((await request("get_simulation_state")).simulationTime,28800);
  assert.deepEqual(pageErrors,[]);
  console.log("PASS actual WASM in workspace, actual live signal polling, observation pause and layout at 1719/1440/1280");
} finally {await client.close();await browser.close();}
