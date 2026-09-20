import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import * as z from "zod/v4";

const server = new McpServer({ name: "traffic-demo", version: "2.0.0" });
const roadIds = z.array(z.number().int().nonnegative()).max(100).optional();
const intersectionIds = z.array(z.number().int().nonnegative()).max(100).optional();

async function dispatch(action, params = {}) {
  const actionId = crypto.randomUUID();
  try {
    const response = await fetch("http://127.0.0.1:30141/api/simulation-demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actionId, action, params }),
      signal: AbortSignal.timeout(65000),
    });
    if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("无法访问 Traffic Pi，请确认本机服务已启动且未启用访问密码。");
    const result = await response.json();
    return { isError: !response.ok || result.status === "failed", content: [{ type: "text", text: JSON.stringify(result, null, 2) }], structuredContent: result };
  } catch (error) {
    const result = { actionId, status: "failed", simulationTime: null, result: null, error: error instanceof Error ? error.message : String(error) };
    return { isError: true, content: [{ type: "text", text: JSON.stringify(result, null, 2) }], structuredContent: result };
  }
}

function tool(name, description, inputSchema, action = name) {
  server.registerTool(name, { description, inputSchema }, async (params) => dispatch(action, params));
}

tool("start_rush_hour_demo", "重置并加载重庆渝中半岛工作日场景。仅在明确要求重置时使用。", {}, "start");
tool("pause_current_simulation", "暂停当前仿真并返回真实状态。", {}, "pause");
tool("resume_current_simulation", "以 1 倍速度继续当前仿真并返回真实状态。", {}, "resume");
tool("speed_up_current_simulation", "将当前仿真提高一档速度并返回真实状态。", {}, "faster");
tool("get_simulation_state", "读取仿真时间、速度、暂停状态、场景和随机种子。", {});
tool("get_road_metrics", "读取道路实时速度、小时流量、排队车辆数和平均累计延误；不传 roadIds 时返回最拥堵道路。", { roadIds });
tool("get_intersection_metrics", "读取路口小时流量、当前相位、排队车辆数和最近一小时平均延误；不传 intersectionIds 时返回最拥堵信号路口。", { intersectionIds });
tool("focus_on_road", "把仿真镜头移动到指定内部道路 ID。", { roadId: z.number().int().nonnegative() });
tool("highlight_roads", "按预警等级在真实仿真画面高亮道路。", { roads: z.array(z.object({ roadId: z.number().int().nonnegative(), level: z.enum(["warning", "severe", "critical"]) })).min(1).max(100) });
tool("clear_highlights", "清除 Traffic Pi 添加的道路高亮。", {});
tool("run_until", "推进到指定仿真秒并在目标时间暂停。目标不能早于当前时间。", { simulationTimeSeconds: z.number().nonnegative().max(172800) });
tool("run_for", "推进指定仿真秒数并在结束时暂停。", { durationSeconds: z.number().positive().max(86400) });
tool("get_signal_plan", "读取指定信号路口的真实相位方案和当前相位。", { intersectionId: z.number().int().nonnegative() });
tool("apply_signal_plan", "修改指定路口各相位时长；首次修改前自动保存原方案。", { intersectionId: z.number().int().nonnegative(), stageDurationsSeconds: z.array(z.number().int().min(5).max(300)).min(1).max(20), offsetSeconds: z.number().int().min(0).max(3600).optional() });
tool("restore_signal_plan", "恢复该路口首次修改前保存的信号方案。", { intersectionId: z.number().int().nonnegative() });
tool("capture_metrics", "运行并保存一个统计时段。方案采集必须指定 baselineCaptureId，系统会从同一基准检查点重跑。", { captureId: z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/), durationSeconds: z.number().positive().max(86400), baselineCaptureId: z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/).optional() });
tool("compare_metrics", "比较两个同场景、同需求、同种子、同统计时段的指标快照。条件不一致时拒绝比较。", { baselineCaptureId: z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/), treatmentCaptureId: z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/) });

await server.connect(new StdioServerTransport());
