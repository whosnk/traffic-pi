import { randomUUID } from "node:crypto";
import { hasJsonContentType, isApiRequestAllowed } from "@/lib/request-security";

type CommandResult = { ok: boolean; result?: unknown; error?: string };
type Command = {
  id: string;
  actionId: string;
  action: string;
  params: Record<string, unknown>;
  viewer: string;
  sessionId?: string;
  toolCallId?: string;
  createdAt: number;
  finish: (result: CommandResult) => void;
};
const shared = globalThis as typeof globalThis & {
  trafficDemoV2?: { viewers: Map<string, { seen: number; sessionId: string }>; cancelled: Map<string, number>; command?: Command };
};
const state = shared.trafficDemoV2 ??= { viewers: new Map<string, { seen: number; sessionId: string }>(), cancelled: new Map<string, number>() };
const viewerTtlMs = 30_000;

export async function GET(request: Request) {
  if (!isApiRequestAllowed(request)) return new Response("Forbidden", { status: 403 });
  const query = new URL(request.url).searchParams;
  const viewer = query.get("viewer") ?? "";
  if (!/^[a-f0-9-]{36}$/.test(viewer)) return new Response("Invalid viewer", { status: 400 });
  for (const [id, info] of state.viewers) if (Date.now() - info.seen > viewerTtlMs) state.viewers.delete(id);
  state.viewers.set(viewer, { seen: Date.now(), sessionId: query.get("sessionId") ?? "" });
  const pending = state.command;
  if (pending?.sessionId) {
    const matches = [...state.viewers].filter(([, info]) => info.sessionId === pending.sessionId);
    if (matches.length > 1) pending.finish({ ok: false, error: "当前会话有多个接收窗口，请只保留一个窗口后重试。" });
    else if (!pending.viewer && matches.length === 1) pending.viewer = matches[0][0];
  }
  const command = state.command?.viewer === viewer ? {
    id: state.command.id,
    actionId: state.command.actionId,
    action: state.command.action,
    params: state.command.params,
    sessionId: state.command.sessionId,
    toolCallId: state.command.toolCallId,
    createdAt: state.command.createdAt,
  } : null;
  return Response.json({ command }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request) {
  if (!isApiRequestAllowed(request) || !hasJsonContentType(request)) return new Response("Forbidden", { status: 403 });
  let body;
  try { body = await request.json(); } catch { return new Response("Invalid JSON", { status: 400 }); }
  if (body?.action === "cancel_detection") {
    for (const [key, at] of state.cancelled) if (Date.now() - at > 305000) state.cancelled.delete(key);
    if (typeof body.sessionId !== "string" || typeof body.toolCallId !== "string") return new Response("Invalid identity", { status: 400 });
    state.cancelled.set(`${body.sessionId}:${body.toolCallId}`, Date.now());
    const command = state.command;
    if (command?.sessionId && command.sessionId === body.sessionId && command.toolCallId === body.toolCallId) command.finish({ ok: false, error: "检测已中止。" });
    return Response.json({ ok: true });
  }
  if (body?.action === "unregister") {
    if (state.viewers.get(body.viewer)?.sessionId === body.sessionId) state.viewers.delete(body.viewer);
    const command = state.command;
    if (command && command.sessionId === body.sessionId && command.viewer === body.viewer) command.finish({ ok: false, error: "接收窗口已关闭或切换会话，检测已中止。" });
    return Response.json({ ok: true });
  }
  if (body?.action === "ack") {
    if (!state.command || state.command.id !== body.id || state.command.viewer !== body.viewer) return new Response("Expired command", { status: 409 });
    const info = state.viewers.get(body.viewer);
    if (info) state.viewers.set(body.viewer, { ...info, seen: Date.now() });
    state.command.finish({ ok: body.ok !== false, result: body.result, error: typeof body.error === "string" ? body.error : undefined });
    return Response.json({ ok: true });
  }
  const actions = [
    "start", "pause", "resume", "faster", "get_simulation_state", "get_road_metrics",
    "get_intersection_metrics", "focus_on_road", "highlight_roads", "clear_highlights",
    "run_until", "run_for", "get_signal_plan", "apply_signal_plan", "restore_signal_plan",
    "capture_metrics", "compare_metrics", "detect_congestion",
  ];
  if (!actions.includes(body?.action)) return new Response("Unknown action", { status: 400 });
  if (body.params !== undefined && (!body.params || typeof body.params !== "object" || Array.isArray(body.params))) return new Response("Invalid params", { status: 400 });
  const detection = body.action === "detect_congestion";
  if (detection && (typeof body.sessionId !== "string" || !body.sessionId || typeof body.toolCallId !== "string" || !body.toolCallId)) return Response.json({ error: "缺少扩展注入的会话和工具调用标识，请重新加载交通 MCP。" }, { status: 400 });
  if (detection && state.cancelled.has(`${body.sessionId}:${body.toolCallId}`)) return Response.json({ error: "检测已中止，请发起新的工具调用。" }, { status: 409 });
  const viewers = [...state.viewers].filter(([, info]) => Date.now() - info.seen < viewerTtlMs && (!detection || info.sessionId === body.sessionId));
  if (viewers.length > 1 || (!detection && viewers.length !== 1)) return Response.json({ error: `检测到 ${viewers.length} 个接收窗口。请只保留一个前台仿真工作台，打开后等待接收状态刷新。` }, { status: 409 });
  if (state.command) return Response.json({ error: "已有演示正在启动，请稍后再试。" }, { status: 409 });
  const actionId = typeof body.actionId === "string" && /^[a-zA-Z0-9_-]{1,80}$/.test(body.actionId) ? body.actionId : randomUUID();
  const received = await new Promise<CommandResult>((resolve) => {
    const timer = setTimeout(() => finish({ ok: false, error: "浏览器执行超时。" }), detection ? 300000 : 60000);
    const heartbeat = detection ? setInterval(() => {
      const command = state.command;
      if (command?.viewer && Date.now() - (state.viewers.get(command.viewer)?.seen ?? 0) > viewerTtlMs) finish({ ok: false, error: "接收窗口失去连接，检测已中止。" });
      else if (command && !command.viewer && Date.now() - command.createdAt >= 180000) finish({ ok: false, error: "准备画面超时：未找到当前会话的接收窗口。" });
    }, 1000) : undefined;
    const abort = () => finish({ ok: false, error: "检测请求已中止。" });
    function finish(value: CommandResult) {
      if (state.command?.actionId !== actionId) return;
      clearTimeout(timer);
      clearInterval(heartbeat);
      request.signal.removeEventListener("abort", abort);
      state.command = undefined;
      resolve(value);
    }
    state.command = { id: randomUUID(), actionId, action: body.action, params: body.params ?? {}, viewer: viewers[0]?.[0] ?? "", finish, createdAt: Date.now(), ...(detection ? { sessionId: body.sessionId, toolCallId: body.toolCallId } : {}) };
    if (detection) { request.signal.addEventListener("abort", abort, { once: true }); if (request.signal.aborted) abort(); }
  });
  if (!received.ok) return Response.json({ actionId, status: "failed", simulationTime: null, result: null, error: received.error ?? "浏览器执行失败。" }, { status: 502 });
  const result = received.result && typeof received.result === "object" ? received.result as Record<string, unknown> : { value: received.result };
  return Response.json({ actionId, status: body.action === "start" ? "loading" : "completed", simulationTime: result.simulationTime ?? null, result, error: null });
}
