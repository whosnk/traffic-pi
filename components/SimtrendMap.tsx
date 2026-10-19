"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { SimtrendMapData, SimtrendSelection } from "@/lib/simtrend-types";

export function SimtrendMap({ data, selection, onSelect }: { data: SimtrendMapData; selection: SimtrendSelection | null; onSelect: (value: SimtrendSelection) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const select = useEffectEvent(onSelect);
  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | undefined;
    void import("maplibre-gl").then(maplibre => {
      if (disposed || !container.current) return;
      maplibre.setWorkerUrl("/api/maplibre/maplibre-gl-worker.mjs");
      const map = new maplibre.Map({
        container: container.current, center: data.center, zoom: data.zoom,
        dragRotate: false, pitchWithRotate: false,
        style: { version: 8, sources: data.synthetic ? {} : {
          osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" },
        }, layers: [
          { id: "background", type: "background", paint: { "background-color": "#eaf0ee" } },
          ...(!data.synthetic ? [{ id: "osm", type: "raster" as const, source: "osm" }] : []),
        ] },
      });
      mapRef.current = map;
      map.addControl(new maplibre.NavigationControl({ showCompass: false }));
      observer = new ResizeObserver(() => map.resize());
      observer.observe(container.current);
      map.on("error", () => setError("底图加载受限时仍可点选仿真路网，也可使用下方道路搜索。"));
      map.on("load", () => {
        map.addSource("roads", { type: "geojson", data: { type: "FeatureCollection", features: data.edges.map(edge => ({
          type: "Feature", properties: { edge_id: edge.edge_id }, geometry: { type: "LineString", coordinates: edge.coordinates },
        })) } });
        map.addLayer({ id: "road-lines", type: "line", source: "roads", paint: { "line-color": "#16858b", "line-width": 4, "line-offset": 3 } });
        map.addLayer({ id: "road-hits", type: "line", source: "roads", paint: { "line-color": "#16858b", "line-width": 14, "line-opacity": 0.01, "line-offset": 3 } });
        map.addLayer({ id: "selected-road", type: "line", source: "roads", filter: ["==", ["get", "edge_id"], ""], paint: { "line-color": "#de781e", "line-width": 7, "line-offset": 3 } });
        map.addSource("zones", { type: "geojson", data: { type: "FeatureCollection", features: data.zones.map(zone => ({
          type: "Feature", properties: { id: zone.id, edge_id: zone.edge_id, lane_id: zone.lane_id },
          geometry: { type: "Point", coordinates: [zone.longitude, zone.latitude] },
        })) } });
        map.addLayer({ id: "zone-points", type: "circle", source: "zones", paint: { "circle-color": "#de781e", "circle-radius": 9, "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
        map.on("click", event => {
          const hits = map.queryRenderedFeatures(event.point, { layers: ["zone-points", "road-hits"] });
          const hit = hits[0];
          if (!hit) return;
          select({ edge_id: String(hit.properties.edge_id), ...(hit.layer.id === "zone-points" ? { zone_id: String(hit.properties.id), lane_id: String(hit.properties.lane_id) } : {}) });
        });
        map.on("mousemove", event => { map.getCanvas().style.cursor = map.queryRenderedFeatures(event.point, { layers: ["zone-points", "road-hits"] }).length ? "pointer" : ""; });
        const points = data.edges.flatMap(edge => edge.coordinates);
        if (points.length) map.fitBounds([[Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1]))], [Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))]], { padding: 28, duration: 0 });
        map.once("idle", () => setReady(true));
      });
    }).catch(() => setError("地图暂时无法启动，请使用下方道路搜索。"));
    return () => { disposed = true; observer?.disconnect(); mapRef.current?.remove(); mapRef.current = null; };
  }, [data]);
  useEffect(() => {
    if (ready && mapRef.current?.getLayer("selected-road")) mapRef.current.setFilter("selected-road", ["==", ["get", "edge_id"], selection?.edge_id ?? ""]);
  }, [ready, selection]);
  return <div className="simtrend-map-wrap"><div className="simtrend-map" data-ready={ready} ref={container} aria-label="点击道路或上客区选择空间对象" />{error && <small role="status">{error}</small>}<small>{data.synthetic ? "四交叉口为合成路网，使用示意坐标，不代表当地真实道路。" : "南京南站实际仿真路网 · 点选道路，橙色圆点为候选上客区。"}</small></div>;
}
