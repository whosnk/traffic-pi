import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { createJiti } from "jiti";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

const { connectTrafficServer, validateServers } = await createJiti(import.meta.url).import("./traffic-mcp.ts");
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
