import { readFile, realpath } from "node:fs/promises";
import { join, extname } from "node:path";
import { isPathWithinRoots } from "@/lib/path-security";

const root = join(process.cwd(), "third-party", "abstreet", "web", "0.3.49");
const types: Record<string, string> = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".wasm": "application/wasm", ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json" };

export async function GET(_request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (path.some((part) => part === ".." || /[\\:]/.test(part))) return new Response("Forbidden", { status: 403 });
  try {
    const file = await realpath(join(root, ...path));
    if (!isPathWithinRoots(file, new Set([await realpath(root)]))) return new Response("Forbidden", { status: 403 });
    const data = await readFile(file);
    return new Response(data, { headers: { "Content-Type": types[extname(file)] ?? "application/octet-stream", "Content-Length": String(data.length), "X-Content-Type-Options": "nosniff" } });
  } catch {
    return new Response("A/B Street local resource not found", { status: 404 });
  }
}
