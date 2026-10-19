export type SimtrendScenario = {
  scenario_id: string; name: string; description: string;
  intersections: { id: string; name: string }[]; supported_capabilities: string[];
};
export type SimtrendLane = { lane_id: string; index: number; length_m: number; speed_limit_mps: number };
export type SimtrendEdge = { edge_id: string; edge_name: string; lane_count: number; coordinates: [number, number][]; from_node: string; to_node: string };
export type SimtrendSelection = { edge_id: string; lane_id?: string; zone_id?: string };
export type SimtrendMapData = {
  scenario_id: string; name: string; synthetic: boolean; center: [number, number]; zoom: number;
  edges: SimtrendEdge[]; lanes: Record<string, SimtrendLane[]>;
  zones: { id: string; name: string; longitude: number; latitude: number; edge_id: string; lane_id: string; capacity: number; boarding_duration_s: number }[];
};
export type SimtrendArtifact = { id: string; name: string; label: string; kind: string; url: string };
export type SimtrendResult = {
  type?: string; ok: boolean; status?: string; message?: string; scenario_id?: string;
  job_id?: string; tool?: string; data?: Record<string, unknown>; artifacts?: SimtrendArtifact[];
  [key: string]: unknown;
};
export type SimtrendJob = {
  id: string; title: string; tool: string; arguments: Record<string, unknown>; status: string;
  created_at: string; steps: { tool: string; status: string; message?: string }[];
  result?: SimtrendResult; artifacts: SimtrendArtifact[];
};
export async function simtrendRequest<T>(body: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const response = await fetch("/api/simtrend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.message || "SimTrend 请求失败。");
  return data as T;
}
