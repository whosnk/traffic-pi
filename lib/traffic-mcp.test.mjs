import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { mkdir, mkdtemp, writeFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createJiti } from "jiti";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

const jiti = createJiti(import.meta.url);
const { connectTrafficServer, validateServers, createTrafficMcpExtension } = await jiti.import("./traffic-mcp.ts");
const { trustProject } = await jiti.import("./project-trust.ts");
test("rejects duplicate names, invalid transport and invalid stdio parameters", () => {
  const s = { name: "sumo", transport: "http", url: "http://localhost:8000/mcp", enabled: true };
  assert.throws(() => validateServers([s, s]));
  assert.throws(() => validateServers([{ ...s, url: "file:///tmp/a" }]));
  assert.throws(() => validateServers([{ ...s, transport: "stdio", command: "python", args: "server.py" }]));
  assert.equal(validateServers([s])[0].enabled, true);
});
test("discovers and calls real MCP protocol tools over HTTP", async () => {
  const server = new McpServer({ name: "test-only", version: "1" });
  server.registerTool("simulation_state", {}, async () => ({ content: [{ type: "text", text: "test-time=42" }] }));
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: randomUUID });
  await server.connect(transport);
  const http = createServer((req, res) => { void transport.handleRequest(req, res); });
  await new Promise((resolve) => http.listen(0, "127.0.0.1", resolve));
  let connection;
  try {
    connection = await connectTrafficServer({ name: "test", transport: "http", enabled: true, url: `http://127.0.0.1:${http.address().port}/mcp` }, process.cwd());
    assert.equal(connection.tools[0].name, "simulation_state");
    const result = await connection.client.callTool({ name: "simulation_state" });
    assert.equal(result.content[0].text, "test-time=42");
  } finally {
    await connection?.client.close();
    await server.close();
    http.closeAllConnections();
    await new Promise((resolve) => http.close(resolve));
  }
});
test("discovers and calls tools over stdio", async () => {
  const code = `import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'; import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'; const server = new McpServer({name:'test',version:'1'}); server.registerTool('state', {}, async () => ({content:[{type:'text',text:'stdio-ok'}]})); await server.connect(new StdioServerTransport());`;
  const { client, tools } = await connectTrafficServer({ name: "stdio", transport: "stdio", command: process.execPath, args: ["--input-type=module", "-e", code], enabled: true }, process.cwd());
  try {
    assert.equal(tools[0].name, "state");
    assert.equal((await client.callTool({ name: "state" })).content[0].text, "stdio-ok");
  } finally { await client.close(); }
});

test("trusted extension injects session and call identity outside model arguments", async () => {
  const root = await mkdtemp(join(tmpdir(), "traffic-mcp-identity-"));
  const agentDir = join(root, "agent");
  const projectDir = join(root, "project");
  const previous = process.env.PI_CODING_AGENT_DIR;
  process.env.PI_CODING_AGENT_DIR = agentDir;
  const server = new McpServer({ name: "identity", version: "1" });
  server.registerTool("detect_congestion", { inputSchema: {} }, async (args, extra) => ({ content: [{ type: "text", text: "ok" }], structuredContent: { args, identity: extra._meta?.trafficPi } }));
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: randomUUID });
  await server.connect(transport);
  const http = createServer((req, res) => { void transport.handleRequest(req, res); });
  await new Promise(resolve => http.listen(0, "127.0.0.1", resolve));
  const tools = [];
  const events = new Map();
  const pi = { registerTool: tool => tools.push(tool), on: (name, callback) => events.set(name, callback) };
  try {
    await mkdir(join(projectDir, ".pi"), { recursive: true });
    await mkdir(agentDir, { recursive: true });
    await writeFile(join(projectDir, ".pi", "mcp.json"), JSON.stringify([{ name: "identity", enabled: true, transport: "http", url: `http://127.0.0.1:${http.address().port}/mcp` }]));
    await createTrafficMcpExtension(projectDir)(pi);
    assert.equal(tools.length, 0, "Untrusted projects must not connect tools");
    trustProject(projectDir, agentDir);
    await createTrafficMcpExtension(projectDir)(pi);
    assert.equal(tools.length, 1);
    const value = await tools[0].execute("call-from-extension", {}, new AbortController().signal, undefined, { sessionManager: { getSessionId: () => "session-from-extension" } });
    assert.deepEqual(value.details.structuredContent, { args: {}, identity: { sessionId: "session-from-extension", toolCallId: "call-from-extension" } });
  } finally {
    await events.get("session_shutdown")?.();
    await server.close(); http.closeAllConnections();
    await new Promise(resolve => http.close(resolve));
    if (previous === undefined) delete process.env.PI_CODING_AGENT_DIR;
    else process.env.PI_CODING_AGENT_DIR = previous;
    await rm(root, { recursive: true, force: true });
  }
});
