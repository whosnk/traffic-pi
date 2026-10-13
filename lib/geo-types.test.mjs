import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";

const jiti = createJiti(import.meta.url);
const { geoSceneFromMessage, parseGeoScene } = await jiti.import("./geo-types.ts");

const scene = {
  type: "traffic-pi-geo",
  revision: 1,
  sources: [{ id: "roads", data: { type: "FeatureCollection", features: [{ type: "Feature", id: "road-1", geometry: { type: "LineString", coordinates: [[106.5, 29.5], [106.6, 29.6]] }, properties: {} }] } }],
  layers: [{ id: "roads-line", sourceId: "roads", type: "line", color: "#ef4444" }],
};

test("accepts a valid GIS scene and rejects invalid geometry", () => {
  assert.equal(parseGeoScene(scene)?.revision, 1);
  assert.equal(parseGeoScene({ ...scene, sources: [{ ...scene.sources[0], data: { ...scene.sources[0].data, features: [{ ...scene.sources[0].data.features[0], geometry: { type: "LineString", coordinates: [[300, 300]] } }] } }] }), null);
  assert.equal(parseGeoScene({ ...scene, sources: [{ ...scene.sources[0], data: { ...scene.sources[0].data, features: [{ ...scene.sources[0].data.features[0], geometry: { type: "Polygon", coordinates: [[[106, 29], [107, 29], [107, 30], [106, 30]]] } }] } }] }), null);
});

test("extracts a GIS scene from a tool result", () => {
  const message = { role: "toolResult", content: [{ type: "text", text: JSON.stringify({ content: [{ type: "text", text: JSON.stringify({ type: "traffic-pi-geo", scene }) }] }) }] };
  assert.equal(geoSceneFromMessage(message)?.sources[0].data.features[0].id, "road-1");
  assert.equal(geoSceneFromMessage({ role: "toolResult", content: [{ type: "text", text: "ordinary result" }] }), null);
});

test("rejects a scene with more than 1000 features", () => {
  const features = Array.from({ length: 1001 }, (_, index) => ({ type: "Feature", id: index, geometry: { type: "Point", coordinates: [106.5, 29.5] }, properties: {} }));
  assert.equal(parseGeoScene({ ...scene, sources: [{ id: "points", data: { type: "FeatureCollection", features } }], layers: [{ id: "points", sourceId: "points", type: "circle" }] }), null);
});

test("requires unique feature IDs", () => {
  const feature = scene.sources[0].data.features[0];
  assert.equal(parseGeoScene({ ...scene, sources: [{ ...scene.sources[0], data: { ...scene.sources[0].data, features: [{ ...feature, id: "same" }, { ...feature, id: "same" }] } }] }), null);
  assert.equal(parseGeoScene({ ...scene, sources: [{ ...scene.sources[0], data: { ...scene.sources[0].data, features: [{ ...feature, id: undefined }] } }] }), null);
});
