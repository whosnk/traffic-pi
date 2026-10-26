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
  let simulationLoads = 0;
  let lastPrompt = "";
  await page.route("**/abstreet/abstreet.html?**", route => {
    if (route.request().method() === "HEAD") return route.continue();
    simulationLoads++;
    return route.fulfill({ contentType: "text/html", body: `<canvas width="1500" height="900"></canvas><script>
    const base={roadId:7,roadName:'测试道路',intersectionId:3,endpoints:[{intersectionId:3,signalised:true,queueVehicles:12}],map:'../data/system/cn/chongqing/maps/yuzhong_core.bin',randomSeed:42,scene:'weekday',simulationTime:28800,targetStages:[0],signal:{intersectionId:3,offsetSeconds:0,currentStage:0,stages:[{index:0,durationSeconds:30,minimumSeconds:10,fixed:true,movements:[{fromRoadId:7,toRoadId:8,protected:true,crosswalk:false}]},{index:1,durationSeconds:30,minimumSeconds:20,fixed:true,movements:[{fromRoadId:8,toRoadId:7,protected:true,crosswalk:false}]}]},approaches:[{roadId:7,name:'测试道路',toIntersectionId:3,queueVehicles:12,currentWaitingSeconds:50,waitingAtIntersection:3,occupancy:.4,downstreamOccupancy:.2,passedVehicles:10},{roadId:8,name:'交叉方向',toIntersectionId:3,queueVehicles:3,currentWaitingSeconds:5,waitingAtIntersection:1,occupancy:.1,downstreamOccupancy:.1,passedVehicles:3}]};
    window.calls=[]; window.stepDelay=8; window.state=structuredClone(base); window.saved=new Map(); window.failAction='';
    window.trafficPi={ready:true,async request(action,p={}){
      window.calls.push({action,params:p}); if(window.failAction===action)throw new Error('测试恢复失败');
      if(action==='get_view_state')return {width:1500,height:900,moving:false,zoom:8,nativeUi:false,anchor:p.roadId!=null?{x:750,y:450}:null};
      if(action==='get_signal_plan')return {...structuredClone(window.state.signal),stageRemainingSeconds:22,simulationTime:window.state.simulationTime};
      if(action==='get_road_metrics')return {roads:[{roadId:7,name:'测试道路',queueVehicles:12,meanVehicleSpeedKph:4},{roadId:8,name:'交叉方向',queueVehicles:8,meanVehicleSpeedKph:5}],simulationTime:window.state.simulationTime};
      if(action==='mitigation_context')return {...structuredClone(window.state),roadId:p.roadId??7};
      if(action==='mitigation_begin')window.saved.set('origin',structuredClone(window.state));
      if(action==='mitigation_checkpoint')window.saved.set(p.name,structuredClone(window.state));
      if(action==='mitigation_restore'||action==='mitigation_cancel'||action==='mitigation_finish')window.state=structuredClone(window.saved.get(action==='mitigation_cancel'?'origin':p.name));
      if(action==='run_for'){window.state.simulationTime+=p.durationSeconds;await new Promise(r=>setTimeout(r,window.stepDelay));}
      if(action==='apply_signal_plan')window.state.signal.stages.forEach((s,i)=>s.durationSeconds=p.stageDurationsSeconds[i]);
      return {map:'../data/system/cn/chongqing/maps/yuzhong_core.bin',randomSeed:42,scene:'weekday',paused:true,speedMultiplier:5,simulationTime:window.state.simulationTime,capabilities:['traffic-pi-ui-v1','traffic-pi-mitigation-v1','traffic-pi-signal-visual-v1']};
    }};
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
    } else if (path.endsWith("/state")) json = { running: path.includes(primarySession), state: { isStreaming: path.includes(primarySession), isPromptRunning: false } };
    else if (path === "/api/models") json = { models: {}, modelList: [] };
    else if (path === "/api/project-trust") json = { trusted: true, cwd };
    else if (path === "/api/worktrees") json = { projectRoot: cwd, projectKey: cwd, worktrees: [], isGit: false };
    else if (path === "/api/home") json = { home: cwd };
    else if (path === "/api/simulation-demo") return route.continue();
    else if (path.startsWith(`/api/agent/${sessionTag}-`) && route.request().method() === "POST") {
      const command = route.request().postDataJSON();
      if (command.type === "prompt") lastPrompt = command.message;
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
  await run("analyze_congestion_cause","mitigation-first",{roadId:7});
  const workflow=page.getByRole("region",{name:"技能执行流程",exact:true});
  await workflow.getByText(/等待选择方案/).waitFor();
  const dialog=page.locator('[aria-label="拥堵缓解方案"]');
  await dialog.waitFor();
  assert.equal(await workflow.locator("li").count(),6);
  assert.equal(simulationLoads,1);
  const firstFrame=page.frames().find(f=>f.url().includes("abstreet.html"));
  await dialog.getByRole("button",{name:"相位 1",exact:false}).first().click();
  await dialog.getByText(/预览 · 未应用/).first().waitFor();
  assert.ok(await firstFrame.evaluate(()=>window.calls.some(c=>c.action==='set_signal_visualization'&&c.params.previewStage===0)));
  await firstFrame.evaluate(()=>{window.failAction='get_signal_plan';});
  await dialog.getByRole("status").filter({hasText:/状态暂不可用/}).waitFor();
  await firstFrame.evaluate(()=>{window.failAction='';});
  await dialog.getByRole("status").filter({hasText:/相位 1 · 剩余/}).waitFor();
  await page.screenshot({path:".next/signal-visual/selection-desktop.png"});
  await dialog.press("Escape");await dialog.waitFor({state:"hidden"});
  let switchBlocked = false;
  page.once("dialog", async alert => { switchBlocked = /缓解任务/.test(alert.message()); await alert.accept(); });
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "仿真实验", exact: true }).click();
  assert.equal(switchBlocked, true, "等待授权时阻止切换引擎");
  assert.equal(await page.locator("#traffic-workspace").getAttribute("data-view"), "abstreet");
  await page.getByRole("region",{name:"溯源道路详情",exact:true}).waitFor();
  assert.equal(await page.locator(".chat-input-textarea").inputValue(),"缓解分析保留草稿");
  await workflow.getByRole("button",{name:"查看方案",exact:true}).click();
  await dialog.getByRole("button",{name:"选择「小幅调整」并验证",exact:true}).click();
  await page.waitForTimeout(150);
  const grant=JSON.parse(lastPrompt.slice(lastPrompt.indexOf('{'),lastPrompt.lastIndexOf('}')+1));
  assert.match(lastPrompt,/evaluate_signal_plan/);assert.equal(grant.taskId,"mitigation-first");
  await firstFrame.evaluate(()=>{window.stepDelay=70;});
  const evaluation = run("evaluate_signal_plan","mitigation-evaluate",grant);
  await dialog.getByRole("button",{name:"暂停观察",exact:true}).click();
  await workflow.getByRole("status").filter({hasText:/已暂停观察/}).waitFor();
  const frozenTime=await firstFrame.evaluate(()=>window.state.simulationTime);
  await page.waitForTimeout(300);
  assert.equal(await firstFrame.evaluate(()=>window.state.simulationTime),frozenTime);
  await page.screenshot({path:".next/signal-visual/paused-desktop.png"});
  await dialog.getByRole("button",{name:"继续验证",exact:true}).click();
  await firstFrame.evaluate(()=>{window.stepDelay=8;});
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "分析与报告", exact: true }).click();
  await evaluation;
  assert.equal(await page.locator("#traffic-workspace").getAttribute("data-view"), "gis", "隐藏主地图不得中断已授权验证");
  await page.getByRole("navigation", { name: "工作模式" }).getByRole("button", { name: "仿真工作台", exact: true }).click();
  await workflow.getByText(/等待保留或恢复/).waitFor();
  await workflow.getByRole("button",{name:"查看对比",exact:true}).click();
  await dialog.getByText("查看真实效果，再决定配时",{exact:true}).waitFor();
  await page.screenshot({path:".next/mitigation-desktop.png"});
  await dialog.getByRole("region",{name:"配时方案对照"}).count();
  assert.ok(await dialog.locator('svg[aria-label*="排队曲线"]').count()>=2);
  for(const [width,height] of [[1719,889],[1440,900],[1280,720]]){
    await page.setViewportSize({width,height});
    await page.screenshot({path:`.next/signal-visual/decision-${width}.png`});
    const footer=await dialog.getByRole("button",{name:"恢复原配时",exact:true}).boundingBox();
    assert.ok(footer.y>=0 && footer.y+footer.height<=height,"Decision must stay within viewport");
  }
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:"reduce"});
  await page.waitForTimeout(350);
  await workflow.getByRole("button",{name:"查看对比",exact:true}).click();
  const bounds=await dialog.boundingBox();assert.ok(bounds.x>=0&&bounds.width<=390);
  await page.screenshot({path:".next/mitigation-mobile.png"});
  await dialog.getByRole("button",{name:"恢复原配时",exact:true}).click();
  await page.waitForTimeout(150);
  const decision=JSON.parse(lastPrompt.slice(lastPrompt.indexOf('{'),lastPrompt.lastIndexOf('}')+1));
  await run("finalize_signal_trial","mitigation-final",decision);
  await workflow.getByRole("status").filter({hasText:"已恢复原配时与基准轮结束状态"}).waitFor();
  const frame=page.frames().find(f=>f.url().includes("abstreet.html"));
  assert.equal(await frame.evaluate(()=>window.state.signal.stages[0].durationSeconds),30);
  assert.equal(await frame.evaluate(()=>window.state.simulationTime),29220);
  await page.setViewportSize({width:1440,height:900});
  await run("analyze_congestion_cause","mitigation-second",{roadId:7});
  await dialog.getByRole("button",{name:"取消任务并恢复",exact:true}).click();
  await workflow.getByRole("status").filter({hasText:"任务已取消"}).waitFor();
  assert.equal(await frame.evaluate(()=>window.state.simulationTime),29220);
  // Exercise the command/SSE race with the receiver already mounted.
  const earlyResult=await client.callTool({name:"analyze_congestion_cause",arguments:{roadId:7},_meta:{trafficPi:{sessionId:primarySession,toolCallId:"mitigation-before-sse"}}},undefined,{timeout:305000});
  assert.equal(earlyResult.isError,false,JSON.stringify(earlyResult));
  await emit({type:"agent_start"});
  await emit({type:"tool_execution_start",toolCallId:"mitigation-before-sse",toolName:"mcp_demo_analyze_congestion_cause_abcdef012345"});
  await workflow.getByText(/等待选择方案/).waitFor();
  await dialog.getByRole("button",{name:"取消任务并恢复",exact:true}).click();
  await workflow.getByRole("status").filter({hasText:"任务已取消"}).waitFor();
  assert.equal(simulationLoads,1);
  const originalSignal = await frame.evaluate(()=>structuredClone(window.state.signal));
  await run("detect_congestion","retarget-source");
  await page.getByRole("region", {name:"交通工作区",exact:true}).getByRole("button", {name:/^分析结果/}).click();
  const resultsPanel = page.getByRole("complementary", {name:"分析结果",exact:true});
  await resultsPanel.getByRole("button", {name:/历史结果/}).click();
  await resultsPanel.getByRole("button", {name:/当前疑似拥堵道路/}).first().click();
  await emit({type:"agent_start"});
  await resultsPanel.getByRole("button", {name:"分析缓解方案",exact:true}).first().click();
  await resultsPanel.getByRole("alert").filter({hasText:/Agent 正忙/}).waitFor();
  await emit({type:"agent_end"});await emit({type:"agent_settled"});await emit({type:"prompt_done"});
  await resultsPanel.getByRole("button", {name:"收起分析结果",exact:true}).click();
  await page.getByRole("region",{name:"道路详情",exact:true}).getByRole("button",{name:"分析缓解方案",exact:true}).click();
  assert.match(lastPrompt,/presetScenario:false/);
  await run("analyze_congestion_cause","retarget-real",{roadId:7});
  const retargetPrompt = page.waitForRequest(request => request.method() === "POST" && request.url().includes(`/api/agent/${primarySession}`) && request.postData()?.includes("roadId=8"));
  await dialog.getByLabel("改选拥堵道路").selectOption("8");
  const retargetMessage = (await retargetPrompt).postDataJSON().message;
  assert.match(retargetMessage,/roadId=8/);
  assert.match(retargetMessage,/presetScenario:false/);
  const retargeted=await run("analyze_congestion_cause","retarget-new",{roadId:8});
  assert.equal(retargeted.structuredContent.result.preset,undefined);
  await workflow.getByRole("button",{name:"查看方案",exact:true}).click();
  await dialog.getByText(/承接拥堵检测/).waitFor();
  if (await dialog.getByRole("button",{name:"取消任务并恢复",exact:true}).count()) await dialog.getByRole("button",{name:"取消任务并恢复",exact:true}).click();
  await dialog.press("Escape");
  await frame.evaluate(signal=>{window.state.signal=signal;},originalSignal);
  await frame.evaluate(()=>{window.state.signal=null;window.state.targetStages=[];});
  await run("detect_congestion","detection-for-mitigation");
  const roadDetails=page.getByRole("region",{name:"道路详情",exact:true});
  await roadDetails.getByRole("button",{name:"分析缓解方案",exact:true}).click();
  assert.match(lastPrompt,/roadId=7/);assert.match(lastPrompt,/presetScenario:false/);
  assert.equal(await page.getByRole("button",{name:"拥堵治理推演",exact:true}).count(),0);
  await frame.evaluate(()=>{window.state.approaches[0].queueVehicles=99;});
  await run("analyze_congestion_cause","mitigation-explicit-real",{roadId:7});
  await workflow.getByRole("button",{name:"查看方案",exact:true}).click();
  await dialog.getByText("真实 A/B Street 验证 · 本地合成交通", {exact:true}).waitFor();
  assert.equal(await dialog.getByText("预设参数推演 · 非真实验证", {exact:true}).count(), 0);
  await dialog.press("Escape");
  await run("detect_congestion","detection-after-real");
  await roadDetails.getByRole("button",{name:"分析缓解方案",exact:true}).click();
  const beforePreset=await frame.evaluate(()=>({state:structuredClone(window.state),calls:window.calls.length}));
  const presetResult=await run("analyze_congestion_cause","mitigation-preset-mcp",{presetScenario:true});
  assert.match(JSON.stringify(presetResult),/preset/);
  await dialog.getByText("预设参数推演 · 非真实验证", {exact:true}).waitFor();
  await dialog.getByText(/承接拥堵检测.*初始排队 12 辆/).waitFor();
  await dialog.getByText(/目标方向模型排队 12–12 辆/).waitFor();
  await dialog.getByRole("button",{name:"选择「目标方向优先」并验证",exact:true}).waitFor();
  await dialog.press("Escape");
  await workflow.getByText(/工具详情/).click();
  await workflow.getByText("预设参数推演记录", {exact:true}).waitFor();
  await workflow.getByText(/工具详情/).click();
  await workflow.getByRole("button",{name:"查看方案",exact:true}).click();
  await dialog.getByRole("button",{name:"选择「目标方向优先」并验证",exact:true}).click();
  await workflow.getByText(/等待保留或恢复/).waitFor({timeout:60000});
  await dialog.getByRole("button",{name:"保留推演方案",exact:true}).waitFor();
  await page.screenshot({path:".next/mitigation-preset-comparison.png"});
  await dialog.getByRole("button",{name:"保留推演方案",exact:true}).click();
  await workflow.getByRole("status").filter({hasText:"治理闭环完成"}).waitFor();
  assert.equal(await workflow.locator('li[data-state="completed"]').count(),6);
  assert.deepEqual(await frame.evaluate(()=>window.state),beforePreset.state);
  const presetWrites=await frame.evaluate(n=>window.calls.slice(n).filter(c=>["apply_signal_plan","run_for","pause","resume","set_speed"].includes(c.action)),beforePreset.calls);
  assert.deepEqual(presetWrites,[]);
  await dialog.press("Escape");
  await workflow.getByRole("button",{name:"重新检测",exact:true}).click();
  await run("detect_congestion","detection-after-comparison");
  await roadDetails.getByRole("button",{name:"分析缓解方案",exact:true}).click();
  await run("analyze_congestion_cause","mitigation-pending-redetect",{roadId:7,presetScenario:true});
  await dialog.getByRole("button",{name:"取消任务并恢复",exact:true}).waitFor();
  await dialog.press("Escape");
  await run("detect_congestion","detection-replaces-pending");
  await workflow.getByRole("status").filter({hasText:"检测完成"}).waitFor();
  await roadDetails.getByRole("button",{name:"分析缓解方案",exact:true}).click();
  await run("analyze_congestion_cause","mitigation-cancel-button",{roadId:7,presetScenario:true});
  await dialog.getByRole("button",{name:"取消任务并恢复",exact:true}).click();
  await workflow.getByRole("status").filter({hasText:"推演已取消"}).waitFor();
  assert.deepEqual(pageErrors,[]);
  console.log("PASS mitigation MCP/SSE/browser execution, six stages, real user grants, snapshot comparison, dialog Escape, narrow/reduced motion, draft preservation, cancellation");
} finally {await client.close();await browser.close();}
