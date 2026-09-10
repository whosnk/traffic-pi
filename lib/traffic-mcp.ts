import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { Type } from "@earendil-works/pi-ai";
import { defineTool, getAgentDir, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getProjectTrustStatus } from "./project-trust";
import { isExistingPathWithinRoots } from "./path-security";

export interface TrafficServer {
  name: string;
  transport: "stdio" | "http";
  command?: string;
  args?: string[];
  url?: string;
  enabled: boolean;
}

export function validateServers(value: unknown): TrafficServer[] {
  if (!Array.isArray(value) || value.length > 20) throw new Error("服务器配置必须是数组，最多 20 个。");
  const names = new Set<string>();
  return value.map((s) => {
    if (!s || typeof s.name !== "string" || !/^[a-zA-Z0-9_-]{1,40}$/.test(s.name) || names.has(s.name)) throw new Error("服务器名称须唯一，使用英文字母、数字、横线或下划线。");
    names.add(s.name);
    if (typeof s.enabled !== "boolean") throw new Error("enabled 必须为布尔值。");
    if (s.transport === "stdio") {
      if (typeof s.command !== "string" || !s.command.trim() || !Array.isArray(s.args) || s.args.some((a: unknown) => typeof a !== "string")) throw new Error("stdio 需要命令及参数数组。");
      return { name: s.name, transport: "stdio", command: s.command, args: s.args, enabled: s.enabled };
    }
    if (s.transport !== "http" || typeof s.url !== "string") throw new Error("请选择 stdio 或 http。");
    const url = new URL(s.url);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("需要不含用户名和密码的 HTTP(S) URL。");
    return { name: s.name, transport: "http", url: url.href, enabled: s.enabled };
  });
}

export function readTrafficServers(cwd: string): TrafficServer[] {
  const file = join(cwd, ".pi", "mcp.json");
  if (!existsSync(file)) return [];
  if (!isExistingPathWithinRoots(file, new Set([cwd]))) throw new Error("配置路径不能指向项目外部。");
  return validateServers(JSON.parse(readFileSync(file, "utf8")));
}

export async function connectTrafficServer(server: TrafficServer, cwd: string) {
  const client = new Client({ name: "traffic-pi", version: "1.0.0" });
  const transport = server.transport === "stdio"
    ? new StdioClientTransport({ command: server.command!, args: server.args, cwd, stderr: "ignore" })
    : new StreamableHTTPClientTransport(new URL(server.url!));
  const timer = setTimeout(() => { void client.close(); void transport.close(); }, 15000);
  try {
    await client.connect(transport);
    const tools = [];
    let cursor: string | undefined;
    do {
      const page = await client.listTools({ cursor });
      tools.push(...page.tools);
      cursor = page.nextCursor;
    } while (cursor);
    return { client, tools };
  } catch (error) {
    await client.close().catch(() => {});
    await transport.close().catch(() => {});
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export function createTrafficMcpExtension(cwd: string) {
  return async (pi: ExtensionAPI) => {
    if (!getProjectTrustStatus(cwd, getAgentDir()).trusted) return;
    const clients: Client[] = [];
    pi.on("session_shutdown", async () => { await Promise.allSettled(clients.map((client) => client.close())); });
    for (const server of readTrafficServers(cwd).filter((s) => s.enabled)) {
      try {
        const { client, tools } = await connectTrafficServer(server, cwd);
        clients.push(client);
        for (const tool of tools) {
          pi.registerTool(defineTool({
            name: `mcp_${server.name.slice(0, 20)}_${tool.name.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 24)}_${createHash("sha256").update(JSON.stringify([server.name, tool.name])).digest("hex").slice(0, 12)}`,
            label: `${server.name} / ${tool.name}`,
            description: tool.description ?? tool.name,
            parameters: Type.Unsafe<Record<string, unknown>>(tool.inputSchema),
            async execute(_id, args, signal) {
              if (!readTrafficServers(cwd).some((s) => s.enabled && JSON.stringify(s) === JSON.stringify(server))) throw new Error("MCP 配置已改变，请重新加载会话。");
              const result = await client.callTool({ name: tool.name, arguments: args }, undefined, { signal, timeout: 60000 });
              return { content: [{ type: "text" as const, text: JSON.stringify(result) }], details: result };
            },
          }));
        }
      } catch (error) {
        pi.on("session_start", async (_event, ctx) => { ctx.ui.notify(`MCP ${server.name}: ${String(error)}`, "error"); });
      }
    }
    pi.on("before_agent_start", async (event) => ({ systemPrompt: `${event.systemPrompt}\n你是 Traffic Pi 交通智能体。优先使用已连接的交通 MCP 工具完成仿真任务。报告数据来源、场景和仿真时间；工具不可用时说明缺口，不编造指标或执行结果。` }));
  };
}
