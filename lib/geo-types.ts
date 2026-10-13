export type GeoPosition = number[];

export type GeoGeometry = {
  type: "Point" | "MultiPoint" | "LineString" | "MultiLineString" | "Polygon" | "MultiPolygon";
  coordinates: GeoPosition | GeoPosition[] | GeoPosition[][] | GeoPosition[][][];
};

export type GeoFeature = {
  type: "Feature";
  id?: string | number;
  geometry: GeoGeometry | null;
  properties?: Record<string, unknown> | null;
};

export type GeoFeatureCollection = {
  type: "FeatureCollection";
  features: GeoFeature[];
};

export type GeoSceneSource = { id: string; data: GeoFeatureCollection };

export type GeoSceneLayer = {
  id: string;
  sourceId: string;
  type: "line" | "circle" | "fill";
  title?: string;
  visible?: boolean;
  color?: string;
  opacity?: number;
  width?: number;
  radius?: number;
};

export type GeoScene = {
  type: "traffic-pi-geo";
  revision: number;
  title?: string;
  center?: [number, number];
  zoom?: number;
  sources: GeoSceneSource[];
  layers: GeoSceneLayer[];
};

import type { AgentMessage } from "./types";

const MAX_FEATURES = 1000;
const GEOMETRIES = new Set(["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"]);

function position(value: unknown): value is GeoPosition {
  return Array.isArray(value) && value.length >= 2 && value.every((item, index) => index > 1 ? typeof item === "number" && Number.isFinite(item) : typeof item === "number" && Number.isFinite(item)) && value[0] >= -180 && value[0] <= 180 && value[1] >= -90 && value[1] <= 90;
}

function coordinateShape(type: string, value: unknown): boolean {
  if (type === "Point") return position(value);
  if (type === "MultiPoint") return Array.isArray(value) && value.length > 0 && value.every(position);
  if (type === "LineString") return Array.isArray(value) && value.length >= 2 && value.every(position);
  if (type === "MultiLineString") return Array.isArray(value) && value.length > 0 && value.every((line) => Array.isArray(line) && line.length >= 2 && line.every(position));
  if (type === "Polygon") return Array.isArray(value) && value.length > 0 && value.every((ring) => Array.isArray(ring) && ring.length >= 4 && ring.every(position) && JSON.stringify(ring[0]) === JSON.stringify(ring[ring.length - 1]));
  return Array.isArray(value) && value.length > 0 && value.every((polygon) => coordinateShape("Polygon", polygon));
}

function validFeature(value: unknown): value is GeoFeature {
  if (!value || typeof value !== "object") return false;
  const feature = value as Record<string, unknown>;
  if (feature.type !== "Feature") return false;
  if (feature.id !== undefined && typeof feature.id !== "string" && typeof feature.id !== "number") return false;
  if (feature.geometry === null) return true;
  if (!feature.geometry || typeof feature.geometry !== "object") return false;
  const geometry = feature.geometry as Record<string, unknown>;
  return typeof geometry.type === "string" && GEOMETRIES.has(geometry.type) && coordinateShape(geometry.type, geometry.coordinates);
}

export function parseGeoScene(value: unknown): GeoScene | null {
  if (!value || typeof value !== "object") return null;
  const input = value as Record<string, unknown>;
  const revision = typeof input.revision === "number" ? input.revision : NaN;
  if (input.type !== "traffic-pi-geo" || !Number.isInteger(revision) || revision < 0) return null;
  if (!Array.isArray(input.sources) || !Array.isArray(input.layers)) return null;
  const sources: GeoSceneSource[] = [];
  let featureCount = 0;
  const featureIds = new Set<string | number>();
  for (const source of input.sources) {
    if (!source || typeof source !== "object") return null;
    const item = source as Record<string, unknown>;
    const data = item.data as Record<string, unknown> | undefined;
    if (typeof item.id !== "string" || !data || data.type !== "FeatureCollection" || !Array.isArray(data.features)) return null;
    if (!data.features.every((feature) => {
      if (!validFeature(feature) || feature.id === undefined || featureIds.has(feature.id)) return false;
      featureIds.add(feature.id);
      return true;
    })) return null;
    featureCount += data.features.length;
    if (featureCount > MAX_FEATURES) return null;
    sources.push({ id: item.id, data: data as GeoFeatureCollection });
  }
  const sourceIds = new Set<string>();
  for (const source of sources) {
    if (sourceIds.has(source.id)) return null;
    sourceIds.add(source.id);
  }
  const layers: GeoSceneLayer[] = [];
  const layerIds = new Set<string>();
  for (const layer of input.layers) {
    if (!layer || typeof layer !== "object") return null;
    const item = layer as Record<string, unknown>;
    if (typeof item.id !== "string" || layerIds.has(item.id) || typeof item.sourceId !== "string" || !sourceIds.has(item.sourceId)) return null;
    if (item.type !== "line" && item.type !== "circle" && item.type !== "fill") return null;
    if (item.color !== undefined && typeof item.color !== "string") return null;
    if (item.opacity !== undefined && (typeof item.opacity !== "number" || item.opacity < 0 || item.opacity > 1)) return null;
    if (item.width !== undefined && (typeof item.width !== "number" || !Number.isFinite(item.width) || item.width < 0)) return null;
    if (item.radius !== undefined && (typeof item.radius !== "number" || !Number.isFinite(item.radius) || item.radius < 0)) return null;
    layerIds.add(item.id);
    layers.push({
      id: item.id,
      sourceId: item.sourceId,
      type: item.type,
      title: typeof item.title === "string" ? item.title : undefined,
      visible: item.visible !== false,
      color: typeof item.color === "string" ? item.color : undefined,
      opacity: typeof item.opacity === "number" ? item.opacity : undefined,
      width: typeof item.width === "number" ? item.width : undefined,
      radius: typeof item.radius === "number" ? item.radius : undefined,
    });
  }
  const center = Array.isArray(input.center) && input.center.length === 2 && input.center.every((item) => typeof item === "number" && Number.isFinite(item))
    ? [input.center[0], input.center[1]] as [number, number]
    : undefined;
  if (input.center !== undefined && (!center || center[0] < -180 || center[0] > 180 || center[1] < -90 || center[1] > 90)) return null;
  const zoom = typeof input.zoom === "number" && Number.isFinite(input.zoom) ? input.zoom : undefined;
  return {
    type: "traffic-pi-geo",
    revision,
    title: typeof input.title === "string" ? input.title : undefined,
    center,
    zoom,
    sources,
    layers,
  };
}

export const GEO_MAX_FEATURES = MAX_FEATURES;

function findGeoScene(value: unknown): GeoScene | null {
  if (typeof value === "string") {
    try { return findGeoScene(JSON.parse(value)); } catch { return null; }
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const scene = findGeoScene(item);
      if (scene) return scene;
    }
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const input = value as Record<string, unknown>;
  if (input.type === "traffic-pi-geo") return parseGeoScene(input.scene ?? input);
  if (Array.isArray(input.content)) {
    for (const item of input.content) {
      const scene = findGeoScene(item);
      if (scene) return scene;
    }
  }
  if (typeof input.text === "string") return findGeoScene(input.text);
  return null;
}

export function geoSceneFromMessage(message: AgentMessage) {
  if (message.role !== "toolResult") return null;
  return findGeoScene(message.content);
}
