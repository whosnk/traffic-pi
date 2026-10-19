// Real engine smoke test. Requires an existing trusted Traffic Pi dev server.
import assert from "node:assert/strict";
const base = process.env.PI_WEB_TEST_URL || "http://127.0.0.1:30141";
async function request(body) {
  const response = await fetch(base + "/api/simtrend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  assert.equal(response.ok && data.ok, true, JSON.stringify(data));
  return data;
}
async function run(tool, args) {
  let { job } = await request({ action: "start", session_id: "simtrend-backend-smoke", tool, arguments: { scenario_id: "four_intersections", ...args } });
  const deadline = Date.now() + 180000;
  while (["queued", "running"].includes(job.status) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 700));
    ({ job } = await request({ action: "job", job_id: job.id }));
  }
  assert.equal(job.status, "completed", JSON.stringify(job.result));
  console.log("PASS:", tool, job.id);
  return job;
}
for (const [slot, durations] of [["reference", [42, 3, 42, 3]], ["candidate", [30, 3, 54, 3]]]) {
  const job = await run("evaluate_parameterized_signal_plan", { controller_id: "c00", phase_durations: durations, duration_seconds: 60, random_seed: 42, result_slot: slot, render_animation: true });
  assert.ok(job.artifacts.some(item => item.kind === "replay"));
}
const diagnosis = await run("diagnose_simulation_result", { variant: "parameterized", top_n: 3 });
assert.ok(diagnosis.result.data.diagnosis);
const comparison = await run("compare_simulation_runs", { reference: "reference", candidate: "candidate" });
assert.ok(comparison.result.data.comparison);
assert.equal(comparison.result.data.comparison.comparability.strictly_comparable, true);
assert.ok(comparison.artifacts.length);
