export async function controlCurrentSimulation(doc: Document, action: string) {
  if (!["pause", "resume", "faster"].includes(action)) throw new Error("未知仿真操作");
  const canvas = doc.querySelector("canvas");
  const win = doc.defaultView as (Window & typeof globalThis) | null;
  if (!canvas || !win) throw new Error("仿真画布尚未就绪，请等待沙盒加载完成。");
  // Stock sandbox has no exported control API; normalize speed before pause/resume.
  const keys = action === "faster" ? ["ArrowRight"] : ["ArrowLeft", "ArrowLeft", "ArrowLeft", "ArrowLeft", ...(action === "resume" ? ["ArrowRight"] : [])];
  for (const code of keys) {
    for (const type of ["keydown", "keyup"]) {
      canvas.dispatchEvent(new win.KeyboardEvent(type, { key: code, code, keyCode: code === "ArrowLeft" ? 37 : 39, bubbles: true }));
    }
    await new Promise(resolve => setTimeout(resolve, 80));
  }
}
