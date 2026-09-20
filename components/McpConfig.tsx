"use client";
import { useEffect, useState } from "react";
import type { TrafficServer } from "@/lib/traffic-mcp";

export function McpConfig({ cwd }: { cwd: string }) {
  const [servers, setServers] = useState<TrafficServer[]>([]);
  const [name, setName] = useState("traffic");
  const [transport, setTransport] = useState<"stdio" | "http">("http");
  const [endpoint, setEndpoint] = useState("");
  const [args, setArgs] = useState("[]");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [message, setMessage] = useState("");
  const [tools, setTools] = useState<{ name: string; description?: string }[]>([]);
  useEffect(() => {
    let cancelled = false;
    fetch(`/api/mcp?cwd=${encodeURIComponent(cwd)}`).then(async (r) => {
      const data = await r.json();
      if (!r.ok) throw new Error(data.error);
      if (!cancelled) { setServers(data.servers); setLoaded(true); }
    }).catch((e) => { if (!cancelled) setMessage(String(e)); });
    return () => { cancelled = true; };
  }, [cwd]);
  async function submit(action: "save" | "test", next?: TrafficServer[], server?: TrafficServer) {
    setBusy(true); setMessage(""); setTools([]);
    try {
      const response = await fetch("/api/mcp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cwd, action, servers: next, server }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      if (action === "save") { setServers(data.servers); setMessage("已保存到当前项目。关闭设置并刷新页面，确认项目信任后新建任务；已有任务请执行 /reload，单独刷新网页不会重连已有会话。"); }
      else { setTools(data.tools); setMessage(`连接成功，发现 ${data.tools.length} 个工具（测试连接已关闭）。`); }
    } catch (e) { setMessage(String(e)); }
    finally { setBusy(false); }
  }
  function draft(): TrafficServer {
    return { name, transport, enabled: true, ...(transport === "http" ? { url: endpoint } : { command: endpoint, args: JSON.parse(args) }) };
  }
  return <section className="traffic-mcp-panel">
    <span className="traffic-kicker">仿真连接</span><h2>MCP 工具</h2>
    <p>连接当前项目的仿真软件。启用后，交通智能体可在对话中调用服务器工具。</p>
    <form onSubmit={(e) => { e.preventDefault(); try { void submit("save", [...servers.filter((s) => s.name !== name), draft()]); } catch { setMessage("参数必须是 JSON 字符串数组。"); } }}>
      <label>服务器名称<input required value={name} onChange={(e) => setName(e.target.value)} pattern="[a-zA-Z0-9_-]{1,40}" /></label>
      <label>连接方式<select value={transport} onChange={(e) => { setTransport(e.target.value as "stdio" | "http"); setEndpoint(""); }}><option value="http">服务器地址 · 流式 HTTP</option><option value="stdio">本地命令 · stdio</option></select></label>
      <label>{transport === "http" ? "MCP 服务地址" : "可执行命令"}<input required value={endpoint} placeholder={transport === "http" ? "http://127.0.0.1:8000/mcp" : "python"} onChange={(e) => setEndpoint(e.target.value)} /></label>
      {transport === "stdio" && <label>参数（JSON 数组）<input value={args} onChange={(e) => setArgs(e.target.value)} placeholder={'["server.py"]'} /></label>}
      <button disabled={busy || !loaded}>保存并启用</button>
    </form>
    <p role="status">{message}</p>
    {!servers.length && <p>尚未配置仿真服务器。</p>}
    {servers.map((s) => <article key={s.name}><strong>{s.name}</strong><span>{s.transport} · {s.enabled ? "已启用（连接状态未检测）" : "已停用"}</span>
      <button disabled={busy} onClick={() => { setName(s.name); setTransport(s.transport); setEndpoint(s.url ?? s.command ?? ""); setArgs(JSON.stringify(s.args ?? [])); }}>编辑</button>
      <button disabled={busy} onClick={() => void submit("test", undefined, s)}>测试连接 / 工具列表</button>
      <button disabled={busy} onClick={() => void submit("save", servers.map((item) => item.name === s.name ? { ...item, enabled: !item.enabled } : item))}>{s.enabled ? "停用" : "启用"}</button>
    </article>)}
    {tools.map((tool) => <article key={tool.name}><strong>{tool.name}</strong><p>{tool.description}</p></article>)}
  </section>;
}
