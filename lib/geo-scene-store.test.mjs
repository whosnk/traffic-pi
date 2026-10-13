import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";

const jiti = createJiti(import.meta.url);
const { geoSceneStore } = await jiti.import("./geo-scene-store.ts");

const scene = (revision) => ({ type: "traffic-pi-geo", revision, sources: [], layers: [] });

test("keeps sessions isolated and ignores stale revisions", () => {
  geoSceneStore.set("session-a", scene(2));
  geoSceneStore.set("session-a", scene(1));
  geoSceneStore.set("session-b", scene(1));
  assert.equal(geoSceneStore.get("session-a").revision, 2);
  assert.equal(geoSceneStore.get("session-b").revision, 1);
  assert.equal(geoSceneStore.get("missing"), null);
});

test("tracks unread revisions per session without marking future results as viewed", () => {
  geoSceneStore.set("unread-a", scene(0));
  geoSceneStore.set("unread-b", scene(3));
  assert.equal(geoSceneStore.isUnread("unread-a"), true);
  geoSceneStore.markSeen("unread-a", 0);
  assert.equal(geoSceneStore.isUnread("unread-a"), false);
  assert.equal(geoSceneStore.isUnread("unread-b"), true);
  geoSceneStore.set("unread-a", scene(0));
  assert.equal(geoSceneStore.isUnread("unread-a"), false);
  geoSceneStore.set("unread-a", scene(2));
  geoSceneStore.markSeen("unread-a", 1);
  assert.equal(geoSceneStore.isUnread("unread-a"), true);
  geoSceneStore.markSeen("unread-a", 99);
  assert.equal(geoSceneStore.isUnread("unread-a"), false);
  geoSceneStore.set("unread-a", scene(3));
  assert.equal(geoSceneStore.isUnread("unread-a"), true);
  geoSceneStore.markSeen("unread-a", 0);
  assert.equal(geoSceneStore.isUnread("unread-a"), true);
  assert.equal(geoSceneStore.isUnread(null), false);
  assert.equal(geoSceneStore.isUnread("missing"), false);
});
