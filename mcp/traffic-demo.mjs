import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import * as z from "zod/v4";

const server = new McpServer({ name: "traffic-demo", version: "2.0.0" });
const roadIds = z.array(z.number().int().nonnegative()).max(100).optional();
const intersectionIds = z.array(z.number().int().nonnegative()).max(100).optional();

async function dispatch(action, params = {}, extra) {
  const actionId = crypto.randomUUID();
  const detection = ["detect_congestion", "analyze_congestion_cause", "evaluate_signal_plan", "finalize_signal_trial"].includes(action);
  const identity = detection ? extra?._meta?.trafficPi : undefined;
  const cancel = () => { if (identity) void fetch("http://127.0.0.1:30141/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "cancel_detection", ...identity }) }).catch(() => {}); };
  if (detection) extra?.signal?.addEventListener("abort", cancel, { once: true });
  try {
    const response = await fetch("http://127.0.0.1:30141/api/simulation-demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actionId, action, params, ...identity }),
      signal: AbortSignal.any([AbortSignal.timeout(action === "evaluate_signal_plan" ? 1265000 : action === "analyze_congestion_cause" ? 605000 : detection ? 302000 : 65000), ...(extra?.signal ? [extra.signal] : [])]),
    });
    if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("无法访问 Traffic Pi，请确认本机服务已启动且未启用访问密码。");
    const result = await response.json();
    return { isError: !response.ok || result.status === "failed", content: [{ type: "text", text: JSON.stringify(result, null, 2) }], structuredContent: result };
  } catch (error) {
    const result = { actionId, status: "failed", simulationTime: null, result: null, error: error instanceof Error ? error.message : String(error) };
    return { isError: true, content: [{ type: "text", text: JSON.stringify(result, null, 2) }], structuredContent: result };
  } finally { extra?.signal?.removeEventListener("abort", cancel); }
}

function tool(name, description, inputSchema, action = name) {
  server.registerTool(name, { description, inputSchema }, async (params) => dispatch(action, params));
}

function validateGeoScene(scene) {
  if (!scene || typeof scene !== "object" || !Number.isInteger(scene.revision) || scene.revision < 0 || !Array.isArray(scene.sources) || !Array.isArray(scene.layers)) return "场景必须包含 revision、sources 和 layers。";
  let featureCount = 0;
  const sourceIds = new Set();
  const featureIds = new Set();
  for (const source of scene.sources) {
    if (!source || typeof source.id !== "string" || sourceIds.has(source.id) || !source.data || source.data.type !== "FeatureCollection" || !Array.isArray(source.data.features)) return "GeoJSON 数据源无效。";
    sourceIds.add(source.id);
    featureCount += source.data.features.length;
    if (featureCount > 1000) return "单个地图场景最多包含 1000 个要素。";
    for (const feature of source.data.features) {
      if (!feature || feature.type !== "Feature" || (typeof feature.id !== "string" && typeof feature.id !== "number") || featureIds.has(feature.id) || (feature.geometry && !validGeometry(feature.geometry))) return "GeoJSON 要素几何类型或 ID 无效。";
      featureIds.add(feature.id);
    }
  }
  const layerIds = new Set();
  if (scene.layers.some((layer) => !layer || typeof layer.id !== "string" || layerIds.has(layer.id) || !sourceIds.has(layer.sourceId) || !["line", "circle", "fill"].includes(layer.type))) return "地图图层引用或类型无效。";
  for (const layer of scene.layers) layerIds.add(layer.id);
  if (Buffer.byteLength(JSON.stringify(scene), "utf8") > 2_000_000) return "地图场景过大，请先聚合数据。";
  return null;
}

function validGeometry(geometry) {
  if (!geometry || typeof geometry !== "object" || !["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"].includes(geometry.type)) return false;
  const position = (value) => Array.isArray(value) && value.length >= 2 && value.every((item) => typeof item === "number" && Number.isFinite(item)) && value[0] >= -180 && value[0] <= 180 && value[1] >= -90 && value[1] <= 90;
  const line = (value) => Array.isArray(value) && value.length >= 2 && value.every(position);
  const polygon = (value) => Array.isArray(value) && value.length > 0 && value.every((ring) => Array.isArray(ring) && ring.length >= 4 && ring.every(position) && JSON.stringify(ring[0]) === JSON.stringify(ring[ring.length - 1]));
  if (geometry.type === "Point") return position(geometry.coordinates);
  if (geometry.type === "MultiPoint") return Array.isArray(geometry.coordinates) && geometry.coordinates.length > 0 && geometry.coordinates.every(position);
  if (geometry.type === "LineString") return line(geometry.coordinates);
  if (geometry.type === "MultiLineString") return Array.isArray(geometry.coordinates) && geometry.coordinates.length > 0 && geometry.coordinates.every(line);
  if (geometry.type === "Polygon") return polygon(geometry.coordinates);
  return Array.isArray(geometry.coordinates) && geometry.coordinates.length > 0 && geometry.coordinates.every(polygon);
}

server.registerTool("publish_geo_scene", {
  description: "在 Traffic Pi GIS 面板发布道路或交通指标 GeoJSON 图层。Feature.id 应使用稳定的道路 ID。",
  inputSchema: { scene: z.record(z.string(), z.unknown()) },
}, async ({ scene }) => {
  const error = validateGeoScene(scene);
  if (error) return { isError: true, content: [{ type: "text", text: error }] };
  const payload = { type: "traffic-pi-geo", scene: { ...scene, type: "traffic-pi-geo" } };
  return { content: [{ type: "text", text: JSON.stringify(payload) }], structuredContent: payload };
});

tool("start_rush_hour_demo", "重置并加载重庆渝中半岛工作日场景。仅在明确要求重置时使用。", {}, "start");
tool("pause_current_simulation", "暂停当前仿真并返回真实状态。", {}, "pause");
tool("resume_current_simulation", "以 1 倍速度继续当前仿真并返回真实状态。", {}, "resume");
tool("speed_up_current_simulation", "将当前仿真提高一档速度并返回真实状态。", {}, "faster");
tool("get_simulation_state", "读取仿真时间、速度、暂停状态、场景和随机种子。", {});
server.registerTool("detect_congestion", { description: "检测当前 A/B Street 疑似拥堵道路：自动打开当前场景，读取状态和指标，按排队≥5辆且速度≤10km/h筛选前5处，替换高亮并定位。保持当前时间控制状态，不重置或推进。返回采集时间、原始指标和排名；后续查看第几个点使用返回 roadId 调用 focus_on_road。", inputSchema: {} }, async (_params, extra) => dispatch("detect_congestion", {}, extra));
server.registerTool("analyze_congestion_cause", { description: "分析并缓解当前拥堵：关联一处目标道路、信号相位和下游排队，观察最多两个周期并暂停，展示溯源证据与候选配时等待用户选择。不自动应用方案；无 roadId 时选择当前首位疑似拥堵。用户明确要求预设场景、推演或展示完整治理闭环时，可传 presetScenario:true，采用预设模型生成方案，选择与验证由页面完成；该模式不修改真实仿真配时，结果不能当作实测。", inputSchema: { roadId: z.number().int().nonnegative().optional(), presetScenario: z.boolean().optional() } }, async (params, extra) => dispatch("analyze_congestion_cause",params,extra));
for (const name of ["evaluate_signal_plan", "finalize_signal_trial"]) server.registerTool(name, {
  description: name === "evaluate_signal_plan" ? "仅在用户通过方案面板选定后，按面板提供的 taskId、approvalToken、version 从同起点验证原配时与选定方案。不得自行生成授权标识。" : "仅在用户通过结果面板决定保留或恢复后，提交面板提供的 taskId、approvalToken、version。不得自行选择。",
  inputSchema: { taskId:z.string().min(1), approvalToken:z.string().uuid(), version:z.number().int().positive() },
}, async(params,extra)=>dispatch(name,params,extra));
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
