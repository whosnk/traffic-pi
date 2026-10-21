import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { createJiti } from "jiti";
const { GET, POST } = await createJiti(import.meta.url, { alias: { "@": process.cwd() } }).import("./route.ts");
const url = "http://localhost/api/simulation-demo";
const post = (body, signal) => POST(new Request(url, { method: "POST", headers: { Host: "localhost", "Content-Type": "application/json" }, body: JSON.stringify(body), signal }));
const poll = (viewer, sessionId) => GET(new Request(`${url}?viewer=${viewer}&sessionId=${sessionId}`, { headers: { Host: "localhost" } }));
const reset = () => { globalThis.trafficDemoV2.viewers.clear(); globalThis.trafficDemoV2.cancelled.clear(); };
const detection = (sessionId = "a", toolCallId = randomUUID()) => ({ action: "detect_congestion", sessionId, toolCallId });
test("requires injected identity and preserves ordinary no-viewer error", async () => {
  reset();
  assert.equal((await post({ action: "detect_congestion" })).status, 400);
  assert.equal((await post({ action: "get_simulation_state" })).status, 409);
});

test("mitigation cancellation matches the originating task across later tool calls", async()=>{
  reset();
  const viewer=randomUUID(); await poll(viewer,"mitigation-session");
  const request={action:"evaluate_signal_plan",sessionId:"mitigation-session",toolCallId:"evaluation-call",params:{taskId:"origin-call",approvalToken:randomUUID(),version:1}};
  const response=post(request);
  await new Promise(resolve=>setImmediate(resolve));
  await post({action:"cancel_detection",sessionId:request.sessionId,toolCallId:"origin-call"});
  assert.equal((await response).status,502);
  assert.equal((await post(request)).status,409);
  assert.equal((await post({...request,action:"finalize_signal_trial",toolCallId:"late-finalize"})).status,409);
});
test("waits for matching session registration, then acknowledges exactly once", async () => {
  reset();
  const request = detection();
  const response = post(request);
  const wrong = randomUUID(); const right = randomUUID();
  assert.equal((await (await poll(wrong, "b")).json()).command, null);
  const { command } = await (await poll(right, "a")).json();
  assert.equal(command.sessionId, "a"); assert.equal(command.toolCallId, request.toolCallId);
  assert.equal((await post({ action: "ack", id: command.id, viewer: wrong })).status, 409);
  assert.equal((await post({ action: "ack", id: command.id, viewer: right, result: { simulationTime: 28800 } })).status, 200);
  assert.equal((await response).status, 200);
  assert.equal((await post({ action: "ack", id: command.id, viewer: right })).status, 409);
});
test("single task, duplicate matching windows and cancellation before dispatch", async () => {
  reset();
  await poll(randomUUID(), "a"); await poll(randomUUID(), "a");
  assert.equal((await post(detection())).status, 409);
  reset();
  const request = detection(); const response = post(request);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((await post(detection("b"))).status, 409);
  await post({ ...request, action: "cancel_detection" });
  assert.equal((await response).status, 502);
  assert.equal((await post(request)).status, 409, "Late dispatch cannot restart a cancelled call");
});
test("unregister and HTTP abort fail a pending detection", async () => {
  reset();
  const viewer = randomUUID(); await poll(viewer, "a");
  const response = post(detection());
  await new Promise(resolve => setImmediate(resolve));
  await post({ action: "unregister", viewer, sessionId: "a" });
  assert.match((await (await response).json()).error, /关闭或切换/);
  const controller = new AbortController();
  const aborted = post(detection(), controller.signal);
  await new Promise(resolve => setImmediate(resolve)); controller.abort();
  assert.match((await (await aborted).json()).error, /中止/);
});
test("preparation, overall and lost receiver timeouts fail without a success result", async t => {
  reset(); t.mock.timers.enable({ apis: ["Date", "setTimeout", "setInterval"] });
  const waiting = post(detection()); await new Promise(resolve => setImmediate(resolve));
  t.mock.timers.tick(180001);
  assert.match((await (await waiting).json()).error, /准备画面超时/);
  const viewer = randomUUID(); await poll(viewer, "a");
  const running = post(detection()); await new Promise(resolve => setImmediate(resolve));
  t.mock.timers.tick(30001);
  assert.match((await (await running).json()).error, /失去连接/);
  reset();
  const total = post(detection()); await new Promise(resolve => setImmediate(resolve));
  for (let i = 0; i < 10; i++) { await poll(viewer, "a"); t.mock.timers.tick(29999); }
  t.mock.timers.tick(20);
  assert.match((await (await total).json()).error, /执行超时/);
});
