import assert from "node:assert/strict";
import test from "node:test";
import { createJiti } from "jiti";
const { startMitigation, mitigationStore } = await createJiti(import.meta.url).import("./mitigation-store.ts");

test("explicit real and preset entry retain immutable detection provenance and report a busy Agent", () => {
  const previous = globalThis.window;
  const target = new EventTarget();
  globalThis.window = target;
  let accepted = true;
  let mode;
  const listener = event => { event.detail.handled = true; mode = event.detail.presetScenario; if (!accepted) event.preventDefault(); };
  target.addEventListener("traffic-start-mitigation", listener);
  try {
    const detection = { roads: [{ roadId: 7, queueVehicles: 12 }], simulationTime: 28800 };
    assert.equal(startMitigation("real-entry", 7, undefined, detection, false), true);
    assert.equal(mode, false);
    detection.roads[0].queueVehicles = 99;
    assert.equal(mitigationStore.takeSource("real-entry").result.roads[0].queueVehicles, 12);
    assert.equal(startMitigation("preset-entry", 7, undefined, detection), true);
    assert.equal(mode, true);
    accepted = false;
    assert.equal(startMitigation("busy-entry", 7, undefined, detection, false), false);
    assert.equal(mitigationStore.takeSource("busy-entry"), undefined);
  } finally {
    target.removeEventListener("traffic-start-mitigation", listener);
    globalThis.window = previous;
  }
});
