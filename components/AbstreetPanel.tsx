"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./AbstreetPanel.module.css";
import { controlCurrentSimulation } from "@/lib/simulation-control";
import { congestionRule } from "@/lib/congestion";
import { congestionStore, useCongestionTask } from "@/lib/congestion-store";
import { executeCongestion, type CongestionResult } from "@/lib/congestion-executor";
import { TrafficWorkflow } from "./TrafficWorkflow";
import { startCongestionAnalysis } from "@/lib/traffic-workflow";
import { ObjectDetails } from "./TrafficObjectDetails";

type SimulationState = { paused: boolean; speedMultiplier: number; simulationTime: number; scene?: string; simulationClock?: string; capabilities?: string[] };
type ViewState = { width: number; height: number; moving: boolean; anchor?: { x: number; y: number } | null };

const simulationUrl = "/abstreet/abstreet.html?../data/system/cn/chongqing/scenarios/yuzhong_core/weekday.bin&--time=08:00:00";

export function AbstreetPanel({ open, receiving, sessionId, onViewResults }: { open: boolean; receiving: boolean; sessionId: string | null; onViewResults: () => void }) {
  const [started, setStarted] = useState(false);
  const [error, setError] = useState("");
  const [demo, setDemo] = useState("");
  const viewer = useRef("");
  const pending = useRef("");
  const task = useCongestionTask(sessionId);
  const active = useRef<AbortController | null>(null);
  const [simulation, setSimulation] = useState<SimulationState | null>(null);
  const [nativeUi, setNativeUi] = useState(false);
  const [bridgeReady, setBridgeReady] = useState(false);
  const [controlBusy, setControlBusy] = useState(false);
  const [selectedRoad, setSelectedRoad] = useState<number | null>(null);
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null);
  const [following, setFollowing] = useState(true);
  const [viewResult, setViewResult] = useState<CongestionResult | null>(null);
  const cameraVersion = useRef(0);
  const viewport = useRef<HTMLDivElement>(null);
  const hud = useRef<HTMLDivElement>(null);
  const [safeTop, setSafeTop] = useState(180);
  const ui = useRef({ nativeUi: false, roadId: null as number | null, supported: false });
  const camera = useRef<(roadIds: number[], signal: AbortSignal) => Promise<boolean>>(async () => false);
  const [size, setSize] = useState({ width: 1500, height: 900 });
  const scale = Math.min(1, size.width / 1500);
  const result = viewResult ?? task?.result;
  const roadIndex = result?.roads.findIndex(road => road.roadId === selectedRoad) ?? -1;
  const road = roadIndex >= 0 ? result?.roads[roadIndex] : undefined;
  const cameraParams = useRef((action: string, params: Record<string, unknown> = {}) => params);
  cameraParams.current = (action, params = {}) => {
    if (nativeUi || !["focus_on_road", "fit_roads", "global_view"].includes(action)) return params;
    const rect = viewport.current?.getBoundingClientRect();
    const iframe = viewport.current?.querySelector("iframe");
    if (!rect?.width || !iframe) return params;
    const ratio = iframe.clientWidth / rect.width;
    const top = Math.min((hud.current?.getBoundingClientRect().bottom ?? rect.top) - rect.top + 20, rect.height * .62);
    return { ...params, padding: { top: Math.max(0, top) * ratio, bottom: 56 * ratio, left: 20 * ratio, right: (action === "focus_on_road" && rect.width > 620 ? 290 : 20) * ratio } };
  };
  const request = async (action: string, params: Record<string, unknown> = {}, signal?: AbortSignal) => {
    const doc = viewport.current?.querySelector("iframe")?.contentDocument;
    if (!doc) throw new Error("仿真尚未就绪，请等待加载。");
    return controlCurrentSimulation(doc, action, cameraParams.current(action, params), signal);
  };
  const interruptCamera = () => {
    cameraVersion.current++;
    setFollowing(false);
    if (ui.current.supported) void request("cancel_camera").catch(() => {});
  };
  const focus = async (roadId: number, smooth = true) => {
    const token = ++cameraVersion.current;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    await request("focus_on_road", { roadId, smooth: smooth && !reduced });
    if (token === cameraVersion.current) setSelectedRoad(roadId);
  };
  camera.current = async (roadIds, signal) => {
    const token = ++cameraVersion.current;
    setSelectedRoad(null);
    setFollowing(true);
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    await request("fit_roads", { roadIds, smooth }, signal);
    let view: ViewState;
    do {
      signal.throwIfAborted();
      if (token !== cameraVersion.current) return false;
      await new Promise(resolve => setTimeout(resolve, 80));
      view = await request("get_view_state", {}, signal) as ViewState;
    } while (view.moving);
    if (token !== cameraVersion.current) return false;
    await request("focus_on_road", { roadId: roadIds[0], smooth }, signal);
    do {
      signal.throwIfAborted();
      if (token !== cameraVersion.current) return false;
      await new Promise(resolve => setTimeout(resolve, 80));
      view = await request("get_view_state", {}, signal) as ViewState;
    } while (view.moving);
    setSelectedRoad(roadIds[0]);
    return true;
  };
  useEffect(() => { ui.current.nativeUi = nativeUi; ui.current.roadId = selectedRoad; }, [nativeUi, selectedRoad]);
  useEffect(() => { setSelectedRoad(null); setAnchor(null); setViewResult(null); cameraVersion.current++; }, [sessionId, task?.id]);
  useEffect(() => {
    if (!open || !started) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let cleanupInput = () => {};
    let attached: Document | null = null;
    let lastStateAt = 0;
    const controller = new AbortController();
    async function sync() {
      try {
        const doc = viewport.current?.querySelector("iframe")?.contentDocument;
        const win = doc?.defaultView as (Window & { trafficPi?: { ready: boolean } }) | null;
        if (doc && win?.trafficPi?.ready) {
          if (attached !== doc) {
            cleanupInput();
            ui.current.supported = false;
            setBridgeReady(false);
            const state = await controlCurrentSimulation(doc, "get_simulation_state", {}, controller.signal) as SimulationState;
            const supported = state.capabilities?.includes("traffic-pi-ui-v1") ?? false;
            ui.current.supported = supported;
            setSimulation(state);
            if (supported) await controlCurrentSimulation(doc, "set_native_ui", { enabled: ui.current.nativeUi }, controller.signal);
            attached = doc;
            setBridgeReady(supported);
            let down: { x: number; y: number } | null = null;
            const stop = () => { cameraVersion.current++; setFollowing(false); if (supported) void controlCurrentSimulation(doc, "cancel_camera").catch(() => {}); };
            const pointerDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY }; };
            const pointerMove = (event: PointerEvent) => { if (down && Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) { down = null; stop(); } };
            const pointerUp = () => { down = null; };
            const key = (event: KeyboardEvent) => { if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "+", "-"].includes(event.key)) stop(); };
            doc.addEventListener("pointerdown", pointerDown, true); doc.addEventListener("pointermove", pointerMove, true); doc.addEventListener("pointerup", pointerUp, true); doc.addEventListener("wheel", stop, { passive: true, capture: true }); doc.addEventListener("keydown", key, true);
            cleanupInput = () => { doc.removeEventListener("pointerdown", pointerDown, true); doc.removeEventListener("pointermove", pointerMove, true); doc.removeEventListener("pointerup", pointerUp, true); doc.removeEventListener("wheel", stop, true); doc.removeEventListener("keydown", key, true); };
          }
          if (Date.now() - lastStateAt > 1500) {
            const state = await controlCurrentSimulation(doc, "get_simulation_state", {}, controller.signal) as SimulationState;
            if (!stopped) setSimulation(state);
            lastStateAt = Date.now();
          }
          if (ui.current.supported && ui.current.roadId !== null) {
            const view = await controlCurrentSimulation(doc, "get_view_state", { roadId: ui.current.roadId }, controller.signal) as ViewState;
            if (!stopped && view.anchor) {
              const { x, y } = view.anchor;
              setAnchor(x >= 0 && y >= 0 && x <= view.width && y <= view.height ? { x: x / view.width, y: y / view.height } : null);
            }
          }
        }
      } catch (error) { if (!stopped) setError(String(error)); }
      finally { if (!stopped) timer = setTimeout(() => { void sync(); }, 100); }
    }
    void sync();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); cleanupInput(); };
  }, [open, started, demo]);
  const control = async (action: string, params: Record<string, unknown> = {}) => {
    setControlBusy(true);
    try {
      const data = await request(action, params);
      if (["pause", "resume", "set_speed"].includes(action)) setSimulation(data as SimulationState);
      setError("");
      return true;
    } catch (error) { setError(String(error)); }
    finally { setControlBusy(false); }
  };
  const startAnalysis = () => {
    if (!startCongestionAnalysis(sessionId)) setError("Agent 仍在执行或尚未准备好，请等待或停止当前任务后再开始。");
  };
  useEffect(() => {
    if (task?.status === "failed" || task?.status === "cancelled") {
      active.current?.abort(); cameraVersion.current++;
      const doc = viewport.current?.querySelector("iframe")?.contentDocument;
      if (doc && ui.current.supported) void controlCurrentSimulation(doc, "cancel_camera").catch(() => {});
    }
  }, [task]);
  useEffect(() => {
    if (!receiving || !started) return;
    viewer.current ||= crypto.randomUUID();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const unregister = () => {
      active.current?.abort();
      if (sessionId) congestionStore.cancel(sessionId, "接收窗口已关闭或切换会话，检测已中止。");
      void fetch("/api/simulation-demo", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "unregister", viewer: viewer.current, sessionId: sessionId ?? "" }) }).catch(() => {});
    };
    window.addEventListener("pagehide", unregister);
    async function execute(command: { id: string; action: string; params: Record<string, unknown>; sessionId?: string; toolCallId?: string; createdAt: number }) {
      const controller = new AbortController();
      active.current = controller;
      const signal = controller.signal;
      const detection = command.action === "detect_congestion";
      const cameraStart = cameraVersion.current;
      let ok = false;
      let result: unknown;
      let message = "";
      const deadline = setTimeout(() => controller.abort(new Error("浏览器执行超时。")), detection ? Math.max(1, command.createdAt + 300000 - Date.now()) : 65000);
      try {
        const currentTask = sessionId ? congestionStore.get(sessionId) : null;
        if (detection && (!sessionId || command.sessionId !== sessionId || command.toolCallId !== currentTask?.id || currentTask?.status !== "running")) throw new Error("检测请求已过期，请重新发起检测。");
        if (detection) {
          setError("");
          while (!(viewport.current?.querySelector("iframe")?.contentWindow as Window & { trafficPi?: { ready: boolean } } | null)?.trafficPi?.ready) {
            signal.throwIfAborted();
            if (Date.now() - command.createdAt >= 180000) throw new Error("准备画面超过 180 秒：A/B Street 接口尚未就绪，请检查场景加载。");
            await new Promise(resolve => setTimeout(resolve, 250));
          }
        }
        const doc = viewport.current?.querySelector("iframe")?.contentDocument;
        if (!doc) throw new Error("当前仿真尚未加载。");
        const request = async (action: string, params?: Record<string, unknown>) => {
          const startedAt = Date.now();
          if (detection) congestionStore.recordCall(sessionId!, command.toolCallId!, action, startedAt);
          try {
            const value = await controlCurrentSimulation(doc, action, cameraParams.current(action, params), signal);
            if (detection) congestionStore.recordCall(sessionId!, command.toolCallId!, action, startedAt, Date.now());
            return value;
          } catch (error) {
            if (detection) congestionStore.recordCall(sessionId!, command.toolCallId!, action, startedAt, Date.now(), String(error));
            throw error;
          }
        };
        if (detection && !ui.current.supported) {
          const state = await request("get_simulation_state") as SimulationState;
          if (!state.capabilities?.includes("traffic-pi-ui-v1")) throw new Error("当前仿真包尚未提供新版地图交互接口，请更新仿真包后重新打开。");
        }
        result = detection ? await executeCongestion(request, (stage, text) => {
          if (stage === 3) setSelectedRoad(null);
          congestionStore.progress(sessionId!, command.toolCallId!, stage, text);
        }, signal, { showRoads: async roadIds => {
          if (cameraStart !== cameraVersion.current) return false;
          const startedAt = Date.now();
          congestionStore.recordCall(sessionId!, command.toolCallId!, "地图范围与道路聚焦", startedAt);
          try { const focused = await camera.current(roadIds, signal); congestionStore.recordCall(sessionId!, command.toolCallId!, "地图范围与道路聚焦", startedAt, Date.now()); return focused; }
          catch (error) { congestionStore.recordCall(sessionId!, command.toolCallId!, "地图范围与道路聚焦", startedAt, Date.now(), String(error)); throw error; }
        } }) : await request(command.action, command.params);
        if (!detection && command.action === "focus_on_road") { setSelectedRoad(command.params.roadId as number); setFollowing(true); }
        signal.throwIfAborted();
        setError(""); ok = true;
      } catch (error) { message = error instanceof Error ? error.message : String(error); if (!stopped) setError(message); }
      finally { clearTimeout(deadline); }
      if (stopped || signal.aborted) {
        if (detection && sessionId) congestionStore.cancel(sessionId, message || "检测已中止。");
        return;
      }
      try {
        const response = await fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "ack", id: command.id, viewer: viewer.current, ok, result, error: message }) });
        if (!response.ok) throw new Error("检测确认失败或请求已过期，请重新检测。");
        if (detection) {
          if (ok) {
            congestionStore.result(sessionId!, command.toolCallId!, result as CongestionResult);
            congestionStore.progress(sessionId!, command.toolCallId!, 4, "地图标注完成，正在确认工具结果…");
          } else congestionStore.finish(sessionId!, command.toolCallId!, message);
        }
      } catch (error) { if (detection) congestionStore.finish(sessionId!, command.toolCallId!, String(error)); }
    }
    async function poll() {
      try {
        if (document.visibilityState === "visible" || (sessionId && congestionStore.get(sessionId)?.status === "running")) {
          const response = await fetch(`/api/simulation-demo?viewer=${viewer.current}&sessionId=${encodeURIComponent(sessionId ?? "")}`);
          if (response.ok) {
            const { command } = await response.json();
            if (!stopped && command && pending.current !== command.id) {
              pending.current = command.id;
              if (command.action === "start") setDemo(command.id);
              else void execute(command);
            }
          }
        }
      } finally { if (!stopped) timer = setTimeout(() => { void poll().catch(() => {}); }, 1000); }
    }
    void poll().catch(() => {});
    return () => { stopped = true; clearTimeout(timer); window.removeEventListener("pagehide", unregister); unregister(); };
  }, [receiving, started, sessionId]);
  useEffect(() => {
    const focusRoad = (event: Event) => {
      const detail = (event as CustomEvent<{ sessionId: string; roadId: number; result?: CongestionResult }>).detail;
      if (detail.sessionId !== sessionId) return;
      if (task?.status === "running") { setError("正在检测，请等待检测结束后定位历史结果。"); return; }
      const doc = viewport.current?.querySelector("iframe")?.contentDocument;
      if (!doc) { setError("仿真尚未就绪，请等待加载后再次定位。"); return; }
      cameraVersion.current++;
      setViewResult(detail.result ?? null);
      setSelectedRoad(detail.roadId); setFollowing(true);
      void controlCurrentSimulation(doc, "focus_on_road", cameraParams.current("focus_on_road", { roadId: detail.roadId, smooth: !window.matchMedia("(prefers-reduced-motion: reduce)").matches })).then(() => setError("")).catch(error => setError(String(error)));
    };
    window.addEventListener("traffic-focus-road", focusRoad);
    return () => window.removeEventListener("traffic-focus-road", focusRoad);
  }, [sessionId, task?.status]);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    let resizeTimer: ReturnType<typeof setTimeout>;
    const observer = new ResizeObserver(([entry]) => {
      clearTimeout(resizeTimer);
      if (entry.contentRect.width && entry.contentRect.height) {
        const { width, height } = entry.contentRect;
        resizeTimer = setTimeout(() => setSize({ width, height }), 100);
      }
    });
    observer.observe(element);
    return () => { clearTimeout(resizeTimer); observer.disconnect(); };
  }, []);
  useEffect(() => {
    const element = hud.current;
    if (!element) { setSafeTop(12); return; }
    const observer = new ResizeObserver(() => setSafeTop(element.offsetTop + element.offsetHeight + 12));
    observer.observe(element);
    return () => observer.disconnect();
  }, [nativeUi]);
  if (open && !started) setStarted(true);

  return <>
    <section inert={!open} aria-hidden={!open} className={styles.workspace} aria-label="交通仿真工作台">
      {error && <div className={styles.error} role="alert"><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="关闭提示">×</button></div>}
      <div ref={viewport} className={styles.viewport}>
        {started && <iframe key={demo} title="本地交通仿真" src={simulationUrl} allow="fullscreen" onLoad={() => {
          if (demo) void fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "ack", id: demo, viewer: viewer.current, result: { message: "场景正在重新加载。", simulationTime: null } }) }).catch(() => setError("演示启动确认失败，请重试。"));
        }} style={{ width: size.width / scale, height: size.height / scale, transform: `scale(${scale})`, transformOrigin: "top left" }} />}
        {!nativeUi && <>
          <div ref={hud} className={styles.mapHud}>
          <section className={styles.sceneControls} aria-label="场景与时间控制">
            <small>本地仿真实例</small><strong>重庆 · 渝中半岛</strong>
            <div className={styles.clock}><time>{simulation ? new Date(simulation.simulationTime * 1000).toISOString().slice(11, 19) : "--:--:--"}</time><span>{simulation ? simulation.paused ? "已暂停" : "运行中" : "场景加载中"}</span></div>
            <div className={styles.controlRow}><button type="button" disabled={!bridgeReady || controlBusy} onClick={() => void control(simulation?.paused ? "resume" : "pause")}>{simulation?.paused ? "▶ 继续" : "Ⅱ 暂停"}</button>
              <label>速度<select aria-label="仿真速度" disabled={!bridgeReady || controlBusy} value={simulation?.speedMultiplier ?? 1} onChange={event => void control("set_speed", { speedMultiplier: Number(event.target.value) })}>{[1,5,30,3600].map(speed => <option key={speed} value={speed}>{speed}×</option>)}</select></label></div>
            <small>{bridgeReady ? "控制已就绪" : "等待仿真接口就绪"}</small>
          </section>
          <TrafficWorkflow task={task} onStart={startAnalysis} />
          <section className={styles.overview} aria-label="当前任务概览"><small>当前任务概览</small><strong>{result ? `${result.roads.length} 处疑似拥堵` : task?.status === "running" ? "正在采集与分析" : "暂无检测结果"}</strong>
            {result ? <><span>道路 {roadIndex >= 0 ? roadIndex + 1 : "—"} / {result.roads.length} · 样本 {result.sampledRoadCount} 条</span><small>采集于 {new Date(result.metricsCollectedAt).toLocaleTimeString()}</small>{viewResult && viewResult.metricsCollectedAt !== task?.result?.metricsCollectedAt && <button type="button" onClick={() => { setViewResult(null); setSelectedRoad(null); }}>历史检测 · 返回最新</button>}{!result.roads.length && <span>当前未发现符合筛选条件的道路</span>}{result.roads.length > 0 && <button type="button" onClick={() => { setFollowing(true); void focus(road?.roadId ?? result.roads[0].roadId).catch(error => setError(String(error))); }}>定位当前道路</button>}</> : <span>通过对话或技能卡片开始分析</span>}
            {result && <div className={styles.overviewActions}><button type="button" onClick={onViewResults}>查看分析结果</button></div>}
          </section>
          </div>
          {road && anchor && <ObjectDetails label="道路详情" title={road.name && road.name !== "???" ? road.name : `道路 ${road.roadId}`} subtitle={`道路 ${road.roadId} · ${roadIndex + 1} / ${result!.roads.length}`} anchor={{ x: anchor.x * size.width, y: anchor.y * size.height }} bounds={size} safeTop={safeTop} onClose={() => setSelectedRoad(null)}>
            <span className={styles.severity} data-level={road.level}>{road.level === "critical" ? "红色" : road.level === "severe" ? "橙色" : "黄色"} · 疑似拥堵</span>
            <dl><div><dt>排队车辆</dt><dd>{road.queueVehicles} 辆</dd></div><div><dt>平均车速</dt><dd>{road.meanVehicleSpeedKph.toFixed(1)} km/h</dd></div><div><dt>平均累计延误</dt><dd>{Number.isFinite(road.meanVehicleDelaySeconds) ? `${road.meanVehicleDelaySeconds!.toFixed(1)} 秒` : "未提供"}</dd></div><div><dt>车辆流量</dt><dd>{Number.isFinite((road as {flowVehiclesPerHour?: number}).flowVehiclesPerHour) ? `${(road as {flowVehiclesPerHour?: number}).flowVehiclesPerHour} 辆/小时` : "未提供"}</dd></div></dl>
            <small>采集于 {new Date(result!.metricsCollectedAt).toLocaleTimeString()} · 采集结果</small>
            <div className={styles.roadNavigation}><button type="button" disabled={roadIndex <= 0 || task?.status === "running"} onClick={() => { setFollowing(true); void focus(result!.roads[roadIndex - 1].roadId).catch(error => setError(String(error))); }}>← 上一处</button><button type="button" disabled={roadIndex >= result!.roads.length - 1 || task?.status === "running"} onClick={() => { setFollowing(true); void focus(result!.roads[roadIndex + 1].roadId).catch(error => setError(String(error))); }}>下一处 →</button></div>
          </ObjectDetails>}
        </>}
        <div className={styles.viewActions} aria-label="地图操作">
          {nativeUi ? <button type="button" onClick={() => { void control("set_native_ui", { enabled: false }).then(ok => { if (ok) setNativeUi(false); }); }}>返回统一界面</button> : <>
            <button type="button" disabled={!bridgeReady} onClick={() => { interruptCamera(); void control("zoom_view", { factor: 1.4 }); }} aria-label="放大地图">＋</button>
            <button type="button" disabled={!bridgeReady} onClick={() => { interruptCamera(); void control("zoom_view", { factor: 1 / 1.4 }); }} aria-label="缩小地图">−</button>
            <button type="button" disabled={!bridgeReady} onClick={() => { interruptCamera(); void control("global_view", { smooth: !window.matchMedia("(prefers-reduced-motion: reduce)").matches }); }}>全局</button>
            <button type="button" aria-pressed={following} disabled={!bridgeReady || !result?.roads.length} onClick={() => { setFollowing(true); void focus(road?.roadId ?? result!.roads[0].roadId).catch(error => setError(String(error))); }}>跟随任务</button>
          </>}
        </div>
        <div className={styles.moreActions}>
          {!nativeUi && <button type="button" disabled={!bridgeReady} onClick={async () => { try { await request("set_native_ui", { enabled: true }); setNativeUi(true); setError(""); } catch (error) { setError(String(error)); } }}>更多 · 原生界面</button>}
          <a href={simulationUrl} target="_blank" rel="noopener noreferrer">独立打开</a>
          <button type="button" onClick={async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); } catch { setError("当前浏览器无法切换全屏，可使用独立打开。"); } }}>切换全屏</button>
        </div>
      </div>
      <footer className={styles.footer}><span>{congestionRule}</span><span>共享本地实例 · 收起不暂停</span></footer>
    </section>
  </>;
}
