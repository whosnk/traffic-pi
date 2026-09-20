import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({ name: "traffic-demo", version: "1.0.0" });
for (const [name, action, description] of [
  ["start_rush_hour_demo", "start", "重新加载重庆渝中半岛工作日合成交通场景并重置到 08:00，自动播放早高峰。仅在用户要求重置早高峰演示时使用；控制当前实例请使用其他工具。"],
  ["pause_current_simulation", "pause", "暂停当前沙盒，不刷新页面、不重置时间。速度归一到 1 倍。"],
  ["resume_current_simulation", "resume", "从当前时间继续播放沙盒，速度设为 1 倍，不刷新页面、不重置进度。"],
  ["speed_up_current_simulation", "faster", "当前沙盒加速一档（1、5、30、3600 倍，最大档不变），暂停的 1 倍状态会先恢复播放。不会跳到早高峰或重载场景。"],
]) server.registerTool(name, {
  description: `${description} 需保持一个前台工作台，关闭沙盒弹窗。通过界面快捷键控制；返回发送确认，不读取内部时间、车辆数或播放状态。`,
  inputSchema: {},
}, async () => {
  try {
    const response = await fetch("http://127.0.0.1:30141/api/simulation-demo", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }), signal: AbortSignal.timeout(15000),
    });
    if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("无法访问演示接口，请检查 Traffic Pi 是否启动及是否启用了访问密码。");
    const result = await response.json();
    return { isError: !response.ok, content: [{ type: "text", text: JSON.stringify(result) }] };
  } catch (error) {
    return { isError: true, content: [{ type: "text", text: `启动失败：${error.message}` }] };
  }
});
await server.connect(new StdioServerTransport());
