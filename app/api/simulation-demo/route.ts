import { randomUUID } from "node:crypto";
import { hasJsonContentType, isApiRequestAllowed } from "@/lib/request-security";

type Command = { id: string; action: string; viewer: string; finish: (received: boolean) => void };
const shared = globalThis as typeof globalThis & {
  trafficDemo?: { viewers: Map<string, number>; command?: Command };
};
const state = shared.trafficDemo ??= { viewers: new Map<string, number>() };

export async function GET(request: Request) {
  if (!isApiRequestAllowed(request)) return new Response("Forbidden", { status: 403 });
  const viewer = new URL(request.url).searchParams.get("viewer") ?? "";
  if (!/^[a-f0-9-]{36}$/.test(viewer)) return new Response("Invalid viewer", { status: 400 });
  for (const [id, seen] of state.viewers) if (Date.now() - seen > 4000) state.viewers.delete(id);
  state.viewers.set(viewer, Date.now());
  return Response.json({ command: state.command?.viewer === viewer ? state.command.id : null, action: state.command?.viewer === viewer ? state.command.action : null }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request) {
  if (!isApiRequestAllowed(request) || !hasJsonContentType(request)) return new Response("Forbidden", { status: 403 });
  let body;
  try { body = await request.json(); } catch { return new Response("Invalid JSON", { status: 400 }); }
  if (body?.action === "ack") {
    if (!state.command || state.command.id !== body.id || state.command.viewer !== body.viewer) return new Response("Expired command", { status: 409 });
    state.command.finish(body.ok !== false);
    return Response.json({ ok: true });
  }
  if (!["start", "pause", "resume", "faster"].includes(body?.action)) return new Response("Unknown action", { status: 400 });
  const viewers = [...state.viewers].filter(([, seen]) => Date.now() - seen < 4000);
  if (viewers.length !== 1) return Response.json({ error: `检测到 ${viewers.length} 个接收窗口。请只保留一个前台仿真工作台，打开后自动接收 MCP 演示；切换后等待 4 秒再试。` }, { status: 409 });
  if (state.command) return Response.json({ error: "已有演示正在启动，请稍后再试。" }, { status: 409 });
  // ponytail: one local demo at a time; use session-scoped routing for multi-user operation.
  const received = await new Promise<boolean>((resolve) => {
    const timer = setTimeout(() => finish(false), 12000);
    function finish(value: boolean) {
      clearTimeout(timer);
      state.command = undefined;
      resolve(value);
    }
    state.command = { id: randomUUID(), action: body.action, viewer: viewers[0][0], finish };
  });
  return Response.json(received
    ? body.action === "start"
      ? { status: "loading", message: "浏览器已加载重庆渝中半岛工作日场景，沙盒正在初始化，将从 08:00 开始播放固定种子 42 生成的合成交通。此操作重置了此前进度；未读取实时车辆数。" }
      : { status: "dispatched", action: body.action, message: "已向当前沙盒发送控制快捷键，未刷新页面或重置进度。暂停和继续会将速度归一到 1 倍。请以沙盒时钟和播放按钮为准；未读取内部仿真状态。" }
    : { error: "浏览器未完成控制，可能画布未就绪或指令已过期。请在已加载完成的沙盒中重试。" }, { status: received ? 200 : 504 });
}
