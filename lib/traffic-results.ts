import { useSyncExternalStore } from "react";
import { geoSceneFromMessage, type GeoScene } from "./geo-types";
import type { ToolResultMessage } from "./types";

const titles = {
  publish_geo_scene: "GIS 分析图层",
  get_road_metrics: "道路指标",
  get_intersection_metrics: "路口指标",
  capture_metrics: "指标采集",
  compare_metrics: "方案对比",
} as const;

export type TrafficResult = {
  id: string;
  type: keyof typeof titles;
  title: string;
  receivedAt: number;
  toolName: string;
  data: Record<string, unknown> | GeoScene;
  simulationTime?: unknown;
  unread: boolean;
};

function payload(value: unknown, depth = 0): Record<string, unknown> | null {
  if (depth > 8) return null;
  if (typeof value === "string") {
    try { return payload(JSON.parse(value), depth + 1); } catch { return null; }
  }
  if (Array.isArray(value)) {
    for (const item of value) { const found = payload(item, depth + 1); if (found) return found; }
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const input = value as Record<string, unknown>;
  if (input.isError === true || input.status === "failed") return null;
  if (input.type === "traffic-pi-geo" || input.status === "completed") return input;
  for (const key of ["structuredContent", "content", "text", "details"]) {
    const found = payload(input[key], depth + 1);
    if (found) return found;
  }
  return null;
}

export function trafficResultFromMessage(message: ToolResultMessage): TrafficResult | null {
  if (message.isError || !message.toolCallId) return null;
  const value = payload(message.details) ?? payload(message.content);
  if (!value) return null;
  const scene = geoSceneFromMessage({ ...message, content: [{ type: "text", text: JSON.stringify(value) }] });
  const tool = Object.keys(titles).find(name => message.toolName === name
    || (message.toolName?.startsWith("mcp_") && message.toolName.endsWith(`_${name}_${message.toolName.split("_").at(-1)}`)
      && /^[a-f0-9]{12}$/.test(message.toolName.split("_").at(-1) ?? "")));
  const type = scene ? "publish_geo_scene" : tool as keyof typeof titles | undefined;
  if (!type || (type === "publish_geo_scene" && !scene)) return null;
  if (!scene && (value.status !== "completed" || !value.result || typeof value.result !== "object" || Array.isArray(value.result) || !Object.keys(value.result).length)) return null;
  return {
    id: message.toolCallId, type, title: scene?.title ?? titles[type], receivedAt: Date.now(),
    toolName: message.toolName ?? "publish_geo_scene", data: structuredClone(scene ?? value.result) as TrafficResult["data"],
    simulationTime: value.simulationTime, unread: true,
  };
}

type ResultState = { results: TrafficResult[]; selectedGeoId: string | null; expandedId: string | null };
const empty: ResultState = { results: [], selectedGeoId: null, expandedId: null };
const sessions = new Map<string, ResultState>();
const listeners = new Set<() => void>();
function update(sessionId: string, state: ResultState) {
  sessions.set(sessionId, state);
  for (const listener of listeners) listener();
}

export const trafficResultStore = {
  get(sessionId: string | null) { return sessionId ? sessions.get(sessionId) ?? empty : empty; },
  add(sessionId: string, result: TrafficResult, latestRevision = -1) {
    const state = this.get(sessionId);
    if (state.results.some(item => item.id === result.id)) return false;
    if (result.type === "publish_geo_scene") {
      const revision = (result.data as GeoScene).revision;
      if (revision <= Math.max(latestRevision, ...state.results.filter(item => item.type === "publish_geo_scene").map(item => (item.data as GeoScene).revision))) return false;
    }
    update(sessionId, { ...state, results: [result, ...state.results] });
    return true;
  },
  select(sessionId: string, id: string) {
    const state = this.get(sessionId);
    const result = state.results.find(item => item.id === id);
    if (!result) return;
    update(sessionId, { ...state,
      selectedGeoId: result.type === "publish_geo_scene" ? id : state.selectedGeoId,
      expandedId: id,
      results: state.results.map(item => item.id === id ? { ...item, unread: false } : item),
    });
  },
  latest(sessionId: string) {
    const state = this.get(sessionId);
    update(sessionId, { ...state, selectedGeoId: null });
  },
  subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener); },
};

export function useTrafficResults(sessionId: string | null) {
  return useSyncExternalStore(trafficResultStore.subscribe, () => trafficResultStore.get(sessionId), () => empty);
}
