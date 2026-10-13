"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { GeoFeature, GeoScene } from "@/lib/geo-types";

type Props = { scene: GeoScene | null; active: boolean; focusRequest: number };

function coordinates(value: unknown, output: [number, number][]) {
  if (!Array.isArray(value)) return;
  if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
    output.push([value[0], value[1]]);
    return;
  }
  for (const child of value) coordinates(child, output);
}

function featureCoordinates(feature: GeoFeature) {
  const output: [number, number][] = [];
  if (feature.geometry) coordinates(feature.geometry.coordinates, output);
  return output;
}

export function GeoMapPanel(props: Props) {
  return <GeoMap {...props} />;
}

function GeoMap({ scene, active, focusRequest }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const renderedLayerIds = useRef<string[]>([]);
  const renderedSourceIds = useRef<string[]>([]);
  const [error, setError] = useState("");
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [mapReady, setMapReady] = useState(false);
  const lastFocusRequest = useRef(0);

  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | undefined;
    void import("maplibre-gl").then((maplibre) => {
      if (disposed || !container.current || mapRef.current) return;
      maplibre.setWorkerUrl("/api/maplibre/maplibre-gl-worker.mjs");
      const map = new maplibre.Map({
        container: container.current,
        style: {
          version: 8,
          sources: {
            openstreetmap: {
              type: "raster",
              tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
              tileSize: 256,
              attribution: "© OpenStreetMap contributors",
            },
          },
          layers: [
            { id: "background", type: "background", paint: { "background-color": "#eef2f5" } },
            { id: "openstreetmap", type: "raster", source: "openstreetmap" },
          ],
        },
        center: scene?.center ?? [106.55, 29.56],
        zoom: scene?.zoom ?? 12,
        attributionControl: { compact: true },
        dragRotate: false,
        pitchWithRotate: false,
      });
      mapRef.current = map;
      observer = new ResizeObserver(() => map.resize());
      observer.observe(container.current);
      setMapReady(true);
      map.on("error", (event) => setError(event.error?.message?.includes("tile.openstreetmap.org")
        ? "重庆底图暂时无法加载，请检查网络连接。已发布的分析图层仍可查看。"
        : "GIS 地图加载失败，请刷新页面重试。"));
    }).catch(() => setError("GIS 地图暂时无法启动，请刷新页面重试。"));
    return () => { disposed = true; observer?.disconnect(); mapRef.current?.remove(); mapRef.current = null; setMapReady(false); };
  // The map is mounted once; scene updates are reconciled by the next effect.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const render = () => {
      for (const layerId of [...renderedLayerIds.current].reverse()) if (map.getLayer(layerId)) map.removeLayer(layerId);
      for (const sourceId of [...renderedSourceIds.current].reverse()) if (map.getSource(sourceId)) map.removeSource(sourceId);
      renderedLayerIds.current = [];
      renderedSourceIds.current = [];
      if (!scene) return;
      for (const source of scene.sources) map.addSource(source.id, { type: "geojson", data: source.data as never });
      renderedSourceIds.current = scene.sources.map((source) => source.id);
      for (const layer of scene.layers) {
        const paint = layer.type === "line"
          ? { "line-color": layer.color ?? "#2563eb", "line-width": layer.width ?? 3, "line-opacity": layer.opacity ?? 1 }
          : layer.type === "circle"
            ? { "circle-color": layer.color ?? "#ef4444", "circle-radius": layer.radius ?? 6, "circle-opacity": layer.opacity ?? 1 }
            : { "fill-color": layer.color ?? "#2563eb", "fill-opacity": layer.opacity ?? 0.45 };
        map.addLayer({ id: layer.id, type: layer.type, source: layer.sourceId, layout: { visibility: (visible[layer.id] ?? layer.visible) === false ? "none" : "visible" }, paint } as never);
      }
      renderedLayerIds.current = scene.layers.map((layer) => layer.id);
      setError("");
    };
    if (map.isStyleLoaded()) render(); else map.once("load", render);
    return () => { map.off("load", render); };
  // Visibility changes are handled by the following effect without rebuilding the scene.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapReady, scene]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    for (const layer of scene?.layers ?? []) if (map.getLayer(layer.id)) {
      map.setLayoutProperty(layer.id, "visibility", (visible[layer.id] ?? layer.visible) === false ? "none" : "visible");
    }
  }, [mapReady, scene, visible]);

  const fitToData = useCallback(() => {
    const map = mapRef.current;
    if (!map || !scene) return;
    const points = scene.sources.flatMap((source) => source.data.features.flatMap(featureCoordinates));
    if (!points.length) {
      if (scene.center) map.jumpTo({ center: scene.center, zoom: scene.zoom ?? map.getZoom() });
      return;
    }
    const lngs = points.map(([lng]) => lng);
    const lats = points.map(([, lat]) => lat);
    map.fitBounds([[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]], { padding: 32, duration: 250 });
  }, [scene]);

  useEffect(() => {
    if (!active || !mapReady) return;
    const frame = requestAnimationFrame(() => mapRef.current?.resize());
    return () => cancelAnimationFrame(frame);
  }, [active, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !active || !focusRequest || focusRequest === lastFocusRequest.current) return;
    const focus = () => {
      map.resize();
      fitToData();
      lastFocusRequest.current = focusRequest;
    };
    if (map.isStyleLoaded()) focus(); else map.once("load", focus);
    return () => { map.off("load", focus); };
  }, [active, mapReady, focusRequest, fitToData]);

  return <div className="geo-panel">
    <div className="geo-toolbar">
      <strong>{scene?.title ?? "重庆底图"}</strong>{scene ? <><span>rev {scene.revision}</span><span>{scene.sources.reduce((sum, source) => sum + source.data.features.length, 0)} 个要素</span></> : <span>暂无分析图层</span>}
      <button type="button" onClick={fitToData} disabled={!scene || !mapReady}>缩放到数据</button>
    </div>
    <div ref={container} className="geo-map" aria-label="GIS 地图" />
    {error && <p className="geo-error" role="alert">{error}</p>}
    <div className="geo-layers" aria-label="地图图层"><span>底图：OpenStreetMap · © OpenStreetMap contributors</span>{scene?.layers.map((layer) => <label key={layer.id}><input type="checkbox" checked={(visible[layer.id] ?? layer.visible) !== false} onChange={(event) => setVisible((current) => ({ ...current, [layer.id]: event.target.checked }))} /><span>{layer.title ?? layer.id}</span></label>)}</div>
  </div>;
}
