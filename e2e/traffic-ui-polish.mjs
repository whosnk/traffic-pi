import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { resolve } from "node:path";

const phase = process.argv[2] || "after";
const directory = resolve(".next/ui-polish", phase);
await mkdir(directory, {recursive:true});
const base = process.env.TRAFFIC_PI_BASE_URL || "http://127.0.0.1:30141";
const session = {id:`ui-polish-${crypto.randomUUID()}`,name:"交通分析与方案讨论",cwd:process.cwd(),projectRoot:process.cwd(),projectKey:process.cwd(),created:"2026-10-25T00:00:00Z",modified:"2026-10-25T00:00:00Z",path:"ui-polish.jsonl",messageCount:2,firstMessage:"分析当前拥堵情况"};
const analysis = `当前先确认拥堵位置与信号条件，再决定是否进入配时验证。以下是阅读排版样例，不代表本轮采集结果。

### 观察重点

1. **排队是否持续**：区分短时信号等待与连续多个周期的排队。
2. **下游是否阻塞**：查看出口占用与关联道路，避免只关注目标方向。
3. **方案是否可执行**：保留行人最短通行时间，不能直接修改自适应相位。

### 指标与口径

| 观察对象 | 检查内容 | 时间口径 | 数据要求 |
| --- | --- | --- | --- |
| 目标进口道路 | 平均与最大排队、结束排队 | 每 5 秒仿真时间采样 | 缺失时显示未提供 |
| 关联交叉方向 | 等待车辆秒数、通过车辆数 | 同一检查点与观察时段 | 同时检查其他方向影响 |

使用 \`detect_congestion\` 获取数据，后续通过 \`analyze_congestion_cause\` 检查证据。选择方案后才授权本地仿真写操作。

\`\`\`json
{"tool":"analyze_congestion_cause","presetScenario":false,"note":"保留完整工具参数与来源，长代码行可以横向滚动"}
\`\`\`

**下一步**：在地图卡片查看检测结果。没有合法候选时如实说明原因，不把数据不足解释为没有拥堵。`;
const browser = await chromium.launch({channel:"msedge"});
let client;
try {
  const page = await browser.newPage({viewport:{width:1719,height:889},colorScheme:"dark",reducedMotion:"reduce"});
  const errors = [];
  page.on("pageerror",error=>errors.push(error.message));
  page.on("dialog",dialog=>dialog.accept());
  await page.addInitScript(()=>{
    localStorage.setItem("pi-theme","dark");
    window.__uiStreams=[];
    window.EventSource=class {
      readyState=1;onmessage=null;onerror=null;
      constructor(url){this.url=url;window.__uiStreams.push(this);queueMicrotask(()=>this.onmessage?.({data:JSON.stringify({type:"connected",isStreaming:false})}));}
      close(){this.readyState=2;}addEventListener(){}removeEventListener(){}
    };
  });
  await page.route("**/api/**",route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==="/api/simulation-demo"||path.startsWith("/api/maplibre/"))return route.continue();
    let json={};
    if(path==="/api/sessions")json={sessions:[session],runningSessionIds:[],sessionListVersion:1};
    else if(path==="/api/agent/running")json={sessionIds:[],sessionListVersion:1};
    else if(path===`/api/sessions/${session.id}`)json={info:session,sessionId:session.id,context:{messages:[{role:"user",content:"请分析当前拥堵情况，并说明后续验证流程。"},{role:"assistant",content:[{type:"text",text:analysis}],provider:"Traffic Pi",model:"交通分析"}],entryIds:["user","analysis"],hasMore:false},tree:[]};
    else if(path==="/api/project-trust")json={trusted:true,cwd:process.cwd()};
    else if(path==="/api/models")json={models:{},modelList:[]};
    else if(path==="/api/worktrees")json={worktrees:[],isGit:false};
    else if(path==="/api/home")json={home:process.cwd()};
    else if(path.startsWith("/api/agent/"))json={state:{isStreaming:false},success:true,data:[],tools:[],activeTools:[],commands:[]};
    return route.fulfill({json});
  });
  await page.goto(`${base}/?session=${session.id}`);
  const work=page.getByRole("region",{name:"交通仿真工作台",exact:true});
  await work.getByRole("status").filter({hasText:/正在加载地图/}).waitFor();
  await page.screenshot({path:resolve(directory,"loading-1719.png")});
  await page.waitForFunction(()=>document.querySelector('iframe[title="本地交通仿真"]')?.contentWindow?.trafficPi?.ready,null,{timeout:180000});
  await work.getByText("控制已就绪",{exact:true}).waitFor({state:"attached",timeout:180000});
  const frame=()=>page.frames().find(frame=>frame.url().includes("abstreet.html"));
  const request=(action,params={})=>frame().evaluate(({action,params})=>window.trafficPi.request(action,params),{action,params});
  const records=[];
  for(const [width,height] of [[1719,889],[1440,900],[1280,720]]){
    await page.setViewportSize({width,height});
    await page.waitForTimeout(600);
    const scroll=page.locator('.traffic-chat-column .overflow-y-auto').first();
    await scroll.evaluate(element=>{element.scrollTop=0;});
    const metrics=await work.evaluate(element=>{
      const hud=element.querySelector('[aria-label="场景与时间控制"]').parentElement;
      const rect=target=>{const r=target.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
      const iframe=element.querySelector("iframe");
      return {cards:[...hud.children].map(rect),iframe:rect(iframe),iframeStyle:iframe.getAttribute("style"),chatWidth:document.querySelector(".traffic-chat-column").getBoundingClientRect().width,hudPointerEvents:getComputedStyle(hud).pointerEvents};
    });
    assert.equal(metrics.cards.length,3);
    assert.equal(metrics.hudPointerEvents,"none");
    for(const card of metrics.cards)assert.ok(card.x>=metrics.iframe.x-1&&card.x+card.width<=width+1);
    if(phase!=="before")assert.ok(metrics.cards[1].width<=681,"The task card must remain bounded");
    if(["chat","after"].includes(phase))assert.ok(metrics.chatWidth>=350&&metrics.chatWidth<=380);
    const switchBounds=await work.getByRole("group",{name:"交通场景切换"}).boundingBox();
    assert.ok(switchBounds.y+switchBounds.height<=metrics.iframe.y,"Scene selection stays outside the map");
    assert.equal(await page.evaluate(({x,y})=>document.elementFromPoint(x,y)?.tagName,{x:metrics.cards[0].x+metrics.cards[0].width+5,y:metrics.cards[0].y+15}),"IFRAME","HUD gaps must pass pointer input to the map");
    assert.equal(await work.locator("iframe").count(),1);
    const table=page.locator(".traffic-chat-column .markdown-table-wrap");
    assert.ok(await table.evaluate(element=>element.scrollWidth>element.clientWidth));
    await page.locator(".chat-input-textarea").fill("保留分析草稿");
    assert.equal(await page.locator(".chat-input-textarea").inputValue(),"保留分析草稿");
    await page.screenshot({path:resolve(directory,`city-${width}.png`)});
    await scroll.evaluate(element=>{element.scrollTop=element.scrollHeight;});
    await page.screenshot({path:resolve(directory,`chat-${width}.png`)});
    records.push({width,height,...metrics});
  }
  if(phase==="after"){
    await page.setViewportSize({width:1719,height:889});
    await page.waitForTimeout(600);
    client=new Client({name:"ui-polish-check",version:"1"});
    await client.connect(new StdioClientTransport({command:process.execPath,args:[resolve("mcp/traffic-demo.mjs")],env:{...process.env,TRAFFIC_PI_BASE_URL:base}}));
    const id=`ui-detect-${crypto.randomUUID()}`;
    const emit=event=>page.evaluate(({sessionId,event})=>{
      const stream=window.__uiStreams.findLast(s=>s.readyState===1&&s.url.includes(`/api/agent/${sessionId}/events`));
      if(!stream)throw new Error("Missing UI event stream");
      stream.onmessage({data:JSON.stringify(event)});
    },{sessionId:session.id,event});
    await work.getByRole("button",{name:"检测当前拥堵点",exact:true}).click();
    await page.waitForFunction(sid=>window.__uiStreams.some(s=>s.readyState===1&&s.url.includes(`/api/agent/${sid}/events`)),session.id);
    await emit({type:"agent_start"});
    await emit({type:"tool_execution_start",toolCallId:id,toolName:"mcp_demo_detect_congestion_abcdef012345"});
    await work.getByRole("button",{name:"取消检测",exact:true}).waitFor();
    for(const [width,height] of [[1719,889],[1440,900],[1280,720]]){
      await page.setViewportSize({width,height});await page.waitForTimeout(200);
      const heights=await work.locator('[aria-label="场景与时间控制"]').evaluate(card=>[...card.parentElement.children].map(item=>item.getBoundingClientRect().height));
      if(width>=1440)assert.ok(heights[1]<=heights[0]+8,"Workflow stays close to the original simulation control height");
      await page.screenshot({path:resolve(directory,`task-running-${width}.png`)});
    }
    const result=await client.callTool({name:"detect_congestion",arguments:{},_meta:{trafficPi:{sessionId:session.id,toolCallId:id}}},undefined,{timeout:305000});
    assert.equal(result.isError,false,JSON.stringify(result));
    await emit({type:"tool_execution_end",toolCallId:id,toolName:"mcp_demo_detect_congestion_abcdef012345",result,isError:false});
    await emit({type:"agent_end"});await emit({type:"agent_settled"});await emit({type:"prompt_done"});
    await work.getByRole("status").filter({hasText:"检测完成"}).waitFor();
    assert.equal((await request("get_simulation_state")).paused,true);
    for(const [width,height] of [[1719,889],[1440,900],[1280,720]]){
      await page.setViewportSize({width,height});await page.waitForTimeout(200);
      await page.screenshot({path:resolve(directory,`task-completed-${width}.png`)});
    }
    await page.setViewportSize({width:1719,height:889});
    await work.getByRole("button",{name:"高速公路",exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('iframe[title="本地交通仿真"]')?.src.includes("highway-demo")&&document.querySelector('iframe[title="本地交通仿真"]')?.contentWindow?.trafficPi?.ready,null,{timeout:180000});
    await work.getByText("控制已就绪",{exact:true}).waitFor({state:"attached"});
    await work.getByRole("button",{name:"Ⅱ 暂停",exact:true}).click();
    await work.getByRole("button",{name:"▶ 继续",exact:true}).waitFor();
    await work.getByLabel("仿真速度").selectOption("5");
    assert.equal((await request("get_simulation_state")).speedMultiplier,5);
    const time=(await request("get_simulation_state")).simulationTime;
    await work.getByRole("button",{name:"放大地图",exact:true}).click();
    assert.equal((await request("get_simulation_state")).simulationTime,time);
    await page.screenshot({path:resolve(directory,"highway-1719.png")});
  }
  assert.deepEqual(errors,[]);
  await writeFile(resolve(directory,"layout.json"),JSON.stringify(records,null,2));
  console.log(`PASS ${phase}: real WASM screenshots, three HUD cards, bounded layout, long Markdown/table, independent scroll and draft at 1719/1440/1280`);
}finally{await client?.close();await browser.close();}
