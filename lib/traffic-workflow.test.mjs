import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const jiti = createJiti(import.meta.url);
const { workflowStepState } = await jiti.import("./traffic-workflow.ts");
const { congestionStore } = await jiti.import("./congestion-store.ts");
const { executeCongestion } = await jiti.import("./congestion-executor.ts");

test("workflow stage rendering supports different skills and terminal states", () => {
  const task = { definition: { kind: "other", title: "另一技能", steps: ["加载", "评估", "汇总"] }, stage: 1, status: "running" };
  assert.deepEqual([0, 1, 2].map(i => workflowStepState(task, i)), ["completed", "running", "waiting"]);
  assert.equal(workflowStepState({ ...task, status: "cancelled" }, 1), "cancelled");
  assert.equal(workflowStepState({ ...task, status: "failed" }, 1), "failed");
  assert.equal(workflowStepState({ ...task, status: "completed" }, 2), "completed");
  assert.equal(workflowStepState(null, 0), "waiting");
});

test("task trace separates MCP and internal calls; cancellation rejects late events", () => {
  assert.equal(congestionStore.start("workflow", "task", "mcp_demo_detect_congestion_abcdef012345"), true);
  assert.equal(congestionStore.start("parallel", "pending"), false);
  congestionStore.recordCall("workflow", "task", "get_simulation_state", 100);
  congestionStore.recordCall("workflow", "task", "get_simulation_state", 100, 140);
  assert.deepEqual(congestionStore.get("workflow").calls.map(c => [c.kind, c.endedAt]), [["mcp", undefined], ["internal", 140]]);
  congestionStore.cancel("workflow", "用户停止");
  assert.equal(congestionStore.get("workflow").status, "cancelled");
  congestionStore.finish("workflow", "task");
  congestionStore.result("workflow", "task", { roads: [] });
  assert.equal(congestionStore.get("workflow").result, undefined);
  assert.equal(congestionStore.start("parallel", "pending"), true);
  congestionStore.finish("parallel", "pending");
});

test("manual camera takeover keeps highlights without claiming automatic focus", async () => {
  const calls = [];
  const state = { paused: true, speedMultiplier: 1, simulationTime: 28800 };
  const result = await executeCongestion(async action => {
    calls.push(action);
    return action === "get_road_metrics" ? { roads: [{ roadId: 7, queueVehicles: 12, meanVehicleSpeedKph: 4 }] } : state;
  }, () => {}, new AbortController().signal, { showRoads: async roadIds => { assert.deepEqual(roadIds, [7]); return false; } });
  assert.equal(result.cameraFocused, false);
  assert.match(result.message, /手动接管/);
  assert.ok(calls.includes("highlight_roads"));
  assert.ok(!calls.includes("focus_on_road"));
});

test("stage times come from real transitions and repeated events keep the first timestamp", () => {
  congestionStore.start("timeline", "timeline-task");
  const started = congestionStore.get("timeline");
  assert.equal(started.stageTimes[0], started.startedAt);
  assert.equal(started.stageTimes[1], undefined);
  congestionStore.progress("timeline", "timeline-task", 1, "读取");
  const entered = congestionStore.get("timeline").stageTimes[1];
  assert.ok(entered >= started.startedAt);
  congestionStore.progress("timeline", "timeline-task", 1, "读取更新");
  assert.equal(congestionStore.get("timeline").stageTimes[1], entered);
  congestionStore.cancel("timeline");
  congestionStore.progress("timeline", "timeline-task", 2, "迟到");
  assert.equal(congestionStore.get("timeline").stageTimes[2], undefined);
});
