import type { SimtrendArtifact, SimtrendResult } from "./simtrend-types";

export function resultArtifacts(result: SimtrendResult): SimtrendArtifact[] {
  const roots = [result.run_root, result.data?.run_root];
  const root = roots.find(value => typeof value === "string" && value.replace(/\\/g, "/").includes("/agent_runs/"));
  const run = typeof root === "string" ? root.replace(/\\/g, "/").split("/agent_runs/")[1]?.replace(/\/$/, "") : null;
  return (result.artifacts ?? []).filter(item => {
    if (!/^\/api\/simtrend\/artifacts\/[a-f0-9]{32}\/\d+$/.test(item.url)) return false;
    // Older chat results may still contain historical files in their saved payload.
    return !run || item.label.replace(/\\/g, "/").startsWith(run + "/");
  });
}

export function replayTitle(artifact: SimtrendArtifact): string {
  if (artifact.name.includes("baseline")) return "基线方案";
  if (artifact.name.includes("optimized")) return "优化方案";
  if (artifact.name.includes("reference_demand")) return "原始需求方案";
  if (artifact.name.includes("adjusted_demand")) return "调整需求方案";
  return "仿真方案";
}
