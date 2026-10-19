import { createReadStream } from "node:fs";
import { stat, realpath } from "node:fs/promises";
import { Readable } from "node:stream";
import { relative, resolve, isAbsolute } from "node:path";
import { simtrendCall, simtrendRoot } from "@/lib/simtrend-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ jobId: string; artifactId: string }> }) {
  try {
    const { jobId, artifactId } = await context.params;
    if (!/^[a-f0-9]{32}$/.test(jobId) || !/^\d{1,5}$/.test(artifactId)) throw new Error("无效的结果编号。");
    const info = await simtrendCall({ action: "artifact", job_id: jobId, artifact_id: artifactId });
    if (!info.ok || typeof info.path !== "string") throw new Error("结果文件不存在。");
    const file = await realpath(info.path);
    const root = await realpath(resolve(simtrendRoot(), "simtrend_scenarios"));
    const rel = relative(root, file);
    if (isAbsolute(rel) || rel.startsWith("..") || !rel.split(/[\\/]/).includes("outputs")) throw new Error("结果文件路径无效。");
    const replay = file.endsWith(".gif");
    const size = (await stat(file)).size;
    return new Response(Readable.toWeb(createReadStream(file)) as ReadableStream, { headers: {
      "Content-Type": replay ? "image/gif" : "application/octet-stream",
      "Content-Length": String(size), "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      "Content-Disposition": `${replay ? "inline" : "attachment"}; filename*=UTF-8''${encodeURIComponent(String(info.name))}`,
    } });
  } catch {
    return Response.json({ error: "无法读取该运行结果。" }, { status: 404 });
  }
}
