import { simtrendCall } from "@/lib/simtrend-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const raw = await request.text();
    if (raw.length > 32000) return Response.json({ ok: false, message: "请求过大。" }, { status: 413 });
    const body = JSON.parse(raw);
    if (!body || !["scenarios", "map", "start", "job", "jobs", "incident_draft"].includes(body.action)) {
      return Response.json({ ok: false, message: "无效请求。" }, { status: 400 });
    }
    const result = await simtrendCall(body);
    return Response.json(result, { status: result.ok === false ? 400 : 200 });
  } catch (error) {
    return Response.json({ ok: false, message: error instanceof Error ? error.message : "请求失败。" }, { status: 500 });
  }
}
