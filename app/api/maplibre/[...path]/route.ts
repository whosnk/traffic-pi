import { readFile } from "node:fs/promises";
import { join } from "node:path";

const root = join(process.cwd(), "node_modules", "maplibre-gl", "dist");
const allowed = new Set(["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]);

export async function GET(_request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (path.length !== 1 || !allowed.has(path[0])) return new Response("Not found", { status: 404 });
  try {
    const data = await readFile(join(root, path[0]));
    return new Response(data, { headers: { "Content-Type": "text/javascript; charset=utf-8", "Cache-Control": "public, max-age=31536000, immutable" } });
  } catch {
    return new Response("MapLibre worker not found", { status: 404 });
  }
}
