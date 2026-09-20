type TrafficBridge = {
  ready?: boolean;
  request(action: string, params?: Record<string, unknown>): Promise<unknown>;
};

export async function controlCurrentSimulation(doc: Document, action: string, params: Record<string, unknown> = {}) {
  const canvas = doc.querySelector("canvas");
  const win = doc.defaultView as (Window & typeof globalThis) | null;
  if (!canvas || !win) throw new Error("仿真画布尚未就绪，请等待沙盒加载完成。");
  const bridge = (win as typeof win & { trafficPi?: TrafficBridge }).trafficPi;
  if (bridge) {
    if (!bridge.ready) throw new Error("仿真场景仍在初始化，请等待右侧进入沙盒。");
    return bridge.request(action, params);
  }
  if (!["pause", "resume", "faster"].includes(action)) throw new Error("当前 A/B Street 构建未提供 Traffic Pi 控制接口。");
  // Stock sandbox has no exported control API; normalize speed before pause/resume.
  const keys = action === "faster" ? ["ArrowRight"] : ["ArrowLeft", "ArrowLeft", "ArrowLeft", "ArrowLeft", ...(action === "resume" ? ["ArrowRight"] : [])];
  for (const code of keys) {
    for (const type of ["keydown", "keyup"]) {
      canvas.dispatchEvent(new win.KeyboardEvent(type, { key: code, code, keyCode: code === "ArrowLeft" ? 37 : 39, bubbles: true }));
    }
    await new Promise(resolve => setTimeout(resolve, 80));
  }
  return { status: "dispatched", simulationTime: null };
}
