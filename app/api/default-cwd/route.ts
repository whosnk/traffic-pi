import { NextResponse } from "next/server";
import { existsSync, mkdirSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { allowFileRoot } from "@/lib/file-access";

// POST /api/default-cwd
// Traffic Pi ships project-local MCP tools, so prefer the running project when
// it has an MCP configuration. Generic installs keep the dated home directory.
export async function POST() {
  try {
    const projectDir = process.cwd();
    if (existsSync(join(projectDir, ".pi", "mcp.json"))) {
      allowFileRoot(projectDir);
      return NextResponse.json({ cwd: projectDir });
    }

    const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
    const dir = join(homedir(), `pi-cwd-${date}`);
    mkdirSync(dir, { recursive: true });
    allowFileRoot(dir);
    return NextResponse.json({ cwd: dir });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
