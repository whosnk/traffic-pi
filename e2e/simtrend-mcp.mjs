// Uses the real embedded Python backend, without an LLM or API key.
import assert from "node:assert/strict";
import { createJiti } from "jiti";

const { connectTrafficServer } = await createJiti(import.meta.url).import("../lib/traffic-mcp.ts");
const { client, tools } = await connectTrafficServer({
  name: "simtrend", transport: "stdio", command: process.execPath,
  args: ["bin/simtrend-mcp.mjs"], enabled: true,
}, process.cwd());
const value = response => response.structuredContent ?? JSON.parse(response.content.find(item => item.type === "text").text);
try {
  assert.equal(tools.length, 13);
  const draft = value(await client.callTool({ name: "prepare_incident_task_draft", arguments: {
    scenario_id: "four_intersections", base_revision: 2,
    fields: { edge_id: "e0_c10", lane_id: "e0_c10_1", incident_type: "追尾事故", incident_duration_minutes: 10 },
  } }));
  assert.equal(draft.type, "simtrend-task-draft");
  assert.equal(draft.simulation_started, false);
  assert.equal(draft.form.duration_seconds, null);
  const scenes = value(await client.callTool({ name: "list_simtrend_scenarios", arguments: {} }));
  assert.equal(scenes.count, 2);
  const query = value(await client.callTool({ name: "query_signal_control", arguments: { scenario_id: "four_intersections", controller_id: "c10" } }));
  assert.equal(query.ok, true);
  assert.equal(query.type, "simtrend-result");
  const job = value(await client.callTool({ name: "submit_simtrend_task", arguments: {
    tool: "run_incident_signal_optimization", arguments: { scenario_id: "four_intersections", incident_text: "东进口发生追尾事故" },
  } }));
  let result;
  for (let i = 0; i < 30; i++) {
    result = value(await client.callTool({ name: "get_simtrend_task", arguments: { job_id: job.id } }));
    if (!["queued", "running"].includes(result.status)) break;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  assert.equal(result.status, "clarification_required");
  assert.equal(result.result.simulation_started, false);
  console.log("PASS: 13 tools, real stdio handshake, editable incident draft without simulation, scene/signal queries, async clarification");
} finally { await client.close(); }
