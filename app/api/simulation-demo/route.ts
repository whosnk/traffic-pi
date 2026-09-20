import { randomUUID } from "node:crypto";
import { hasJsonContentType, isApiRequestAllowed } from "@/lib/request-security";

type CommandResult = { ok: boolean; result?: unknown; error?: string };
type Command = {
  id: string;
  actionId: string;
  action: string;
  params: Record<string, unknown>;
  viewer: string;
  finish: (result: CommandResult) => void;
};
const shared = globalThis as typeof globalThis & {
  trafficDemo?: { viewers: Map<string, number>; command?: Command };
};
const state = shared.trafficDemo ??= { viewers: new Map<string, number>() };
const viewerTtlMs = 30_000;

export async function GET(request: Request) {
  if (!isApiRequestAllowed(request)) return new Response("Forbidden", { status: 403 });
  const viewer = new URL(request.url).searchParams.get("viewer") ?? "";
  if (!/^[a-f0-9-]{36}$/.test(viewer)) return new Response("Invalid viewer", { status: 400 });
  for (const [id, seen] of state.viewers) if (Date.now() - seen > viewerTtlMs) state.viewers.delete(id);
  state.viewers.set(viewer, Date.now());
  const command = state.command?.viewer === viewer ? {
    id: state.command.id,
    actionId: state.command.actionId,
    action: state.command.action,
    params: state.command.params,
  } : null;
  return Response.json({ command }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: Request) {
  if (!isApiRequestAllowed(request) || !hasJsonContentType(request)) return new Response("Forbidden", { status: 403 });
  let body;
  try { body = await request.json(); } catch { return new Response("Invalid JSON", { status: 400 }); }
  if (body?.action === "ack") {
    if (!state.command || state.command.id !== body.id || state.command.viewer !== body.viewer) return new Response("Expired command", { status: 409 });
    state.viewers.set(body.viewer, Date.now());
    state.command.finish({ ok: body.ok !== false, result: body.result, error: typeof body.error === "string" ? body.error : undefined });
    return Response.json({ ok: true });
  }
  const actions = [
    "start", "pause", "resume", "faster", "get_simulation_state", "get_road_metrics",
    "get_intersection_metrics", "focus_on_road", "highlight_roads", "clear_highlights",
    "run_until", "run_for", "get_signal_plan", "apply_signal_plan", "restore_signal_plan",
    "capture_metrics", "compare_metrics",
  ];
  if (!actions.includes(body?.action)) return new Response("Unknown action", { status: 400 });
  if (body.params !== undefined && (!body.params || typeof body.params !== "object" || Array.isArray(body.params))) return new Response("Invalid params", { status: 400 });
  const viewers = [...state.viewers].filter(([, seen]) => Date.now() - seen < viewerTtlMs);
  if (viewers.length !== 1) return Response.json({ error: `检测到 ${viewers.length} 个接收窗口。请只保留一个前台仿真工作台，打开后等待接收状态刷新。` }, { status: 409 });
  if (state.command) return Response.json({ error: "已有演示正在启动，请稍后再试。" }, { status: 409 });
  // ponytail: one local demo at a time; use session-scoped routing for multi-user operation.
  const actionId = typeof body.actionId === "string" && /^[a-zA-Z0-9_-]{1,80}$/.test(body.actionId) ? body.actionId : randomUUID();
  const received = await new Promise<CommandResult>((resolve) => {
    const timer = setTimeout(() => finish({ ok: false, error: "浏览器执行超时。" }), 60000);
    function finish(value: CommandResult) {
      clearTimeout(timer);
      state.command = undefined;
      resolve(value);
    }
    state.command = { id: randomUUID(), actionId, action: body.action, params: body.params ?? {}, viewer: viewers[0][0], finish };
  });
  if (!received.ok) return Response.json({ actionId, status: "failed", simulationTime: null, result: null, error: received.error ?? "浏览器执行失败。" }, { status: 502 });
  const result = received.result && typeof received.result === "object" ? received.result as Record<string, unknown> : { value: received.result };
  return Response.json({ actionId, status: body.action === "start" ? "loading" : "completed", simulationTime: result.simulationTime ?? null, result, error: null });
}
