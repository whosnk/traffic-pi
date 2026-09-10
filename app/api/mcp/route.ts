import { NextResponse } from "next/server";
import { existsSync, mkdirSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { getAllowedFileRoots, isExistingFilePathAllowed } from "@/lib/file-access";
import { hasJsonContentType, isApiRequestAllowed } from "@/lib/request-security";
import { getProjectTrustStatus } from "@/lib/project-trust";
import { writePrivateFileAtomicSync } from "@/lib/atomic-file";
import { connectTrafficServer, readTrafficServers, validateServers } from "@/lib/traffic-mcp";

export async function GET(request: Request) {
  if (!isApiRequestAllowed(request)) return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  try {
    const cwd = new URL(request.url).searchParams.get("cwd");
    if (!cwd || !isExistingFilePathAllowed(cwd, await getAllowedFileRoots())) return NextResponse.json({ error: "请先选择项目" }, { status: 403 });
    return NextResponse.json({ servers: readTrafficServers(cwd) });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 400 });
  }
}

export async function POST(request: Request) {
  if (!isApiRequestAllowed(request) || !hasJsonContentType(request)) return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  try {
    const body = await request.json();
    if (typeof body.cwd !== "string" || !isExistingFilePathAllowed(body.cwd, await getAllowedFileRoots())) return NextResponse.json({ error: "请先选择项目" }, { status: 403 });
    const cwd = realpathSync(body.cwd);
    if (body.action === "test") {
      if (!getProjectTrustStatus(cwd, getAgentDir()).trusted) throw new Error("请先在项目提示中信任此项目，然后再测试连接。");
      const server = validateServers([body.server])[0];
      const { client, tools } = await connectTrafficServer(server, cwd);
      await client.close();
      return NextResponse.json({ tools });
    }
    if (body.action !== "save") throw new Error("未知操作");
    const servers = validateServers(body.servers);
    const directory = join(cwd, ".pi");
    const file = join(directory, "mcp.json");
    const roots = new Set([cwd]);
    for (const path of [directory, file]) {
      if (existsSync(path) && !isExistingFilePathAllowed(path, roots)) throw new Error("配置路径不能指向项目外部。");
    }
    mkdirSync(directory, { recursive: true });
    writePrivateFileAtomicSync(file, JSON.stringify(servers, null, 2) + "\n");
    return NextResponse.json({ servers });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 400 });
  }
}
