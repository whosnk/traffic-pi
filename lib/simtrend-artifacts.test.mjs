import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const { resultArtifacts, replayTitle } = await createJiti(import.meta.url).import("./simtrend-artifacts.ts");
const file = (id, folder, name) => ({ id: String(id), name, label: `${folder}/${name}`, kind: "replay", url: `/api/simtrend/artifacts/${"a".repeat(32)}/${id}` });

test("saved results containing seven animations show only the current pair", () => {
  const artifacts = [file(0, "old/baseline", "baseline_replay.gif"), file(1, "old/optimized", "optimized_replay.gif"),
    file(4, "current/baseline", "baseline_replay.gif"), file(16, "current/optimized", "optimized_replay.gif"),
    ...[17, 18, 19].map(id => file(id, `parameterized_${id}/simulation`, "parameterized_replay.gif"))];
  for (const root of ["scenario/outputs/agent_runs/current", ".\\scenario\\outputs\\agent_runs\\current"]) {
    const shown = resultArtifacts({ ok: true, data: { run_root: root }, artifacts });
    assert.deepEqual(shown.map(item => item.id), ["4", "16"]);
    assert.deepEqual(shown.map(replayTitle), ["基线方案", "优化方案"]);
  }
  assert.equal(artifacts.length, 7);
});

test("single-plan replay stays available and invalid file URLs remain excluded", () => {
  const artifact = file(0, "parameterized/simulation", "parameterized_replay.gif");
  assert.equal(resultArtifacts({ ok: true, artifacts: [artifact, { ...artifact, url: "https://example.com/x.gif" }] }).length, 1);
});
