import { useSyncExternalStore } from "react";
import type { GeoScene } from "./geo-types";

const scenes = new Map<string, GeoScene>();
const seenRevisions = new Map<string, number>();
const listeners = new Set<() => void>();

export const geoSceneStore = {
  get(sessionId: string | null) {
    return sessionId ? scenes.get(sessionId) ?? null : null;
  },
  set(sessionId: string, scene: GeoScene) {
    const previous = scenes.get(sessionId);
    if (previous && scene.revision <= previous.revision) return;
    scenes.set(sessionId, scene);
    for (const listener of listeners) listener();
  },
  isUnread(sessionId: string | null) {
    if (!sessionId) return false;
    const scene = scenes.get(sessionId);
    return Boolean(scene && scene.revision > (seenRevisions.get(sessionId) ?? -1));
  },
  markSeen(sessionId: string, revision: number) {
    const scene = scenes.get(sessionId);
    if (!scene) return;
    const next = Math.min(revision, scene.revision);
    if (next <= (seenRevisions.get(sessionId) ?? -1)) return;
    seenRevisions.set(sessionId, next);
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

export function useGeoScene(sessionId: string | null) {
  return useSyncExternalStore(geoSceneStore.subscribe, () => geoSceneStore.get(sessionId), () => null);
}

export function useGeoSceneUnread(sessionId: string | null) {
  return useSyncExternalStore(geoSceneStore.subscribe, () => geoSceneStore.isUnread(sessionId), () => false);
}
