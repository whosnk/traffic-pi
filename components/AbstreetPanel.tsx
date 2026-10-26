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
import { MitigationExecutor } from "@/lib/mitigation-executor";
import { mitigationStore, startMitigation, useMitigationTask } from "@/lib/mitigation-store";
import { mitigationTools, type SignalPlan } from "@/lib/mitigation";
import { MitigationPanel } from "./MitigationPanel";
import { MitigationScenario } from "@/lib/mitigation-scenario";
import { abstreetScenarios, abstreetUrl, sceneIdentityMatches, scenarioActionReason, scenarioSwitchReason, type AbstreetScenario } from "@/lib/traffic-scenarios";
import { abstreetRuntime, useAbstreetRuntime } from "@/lib/abstreet-runtime";

type SimulationState = { busy?: boolean; map?: string; randomSeed?: number; paused: boolean; speedMultiplier: number; simulationTime: number; scene?: string; simulationClock?: string; capabilities?: string[] };
type ViewState = { width: number; height: number; moving: boolean; anchor?: { x: number; y: number } | null };



export function AbstreetPanel({ open, receiving, sessionId, onViewResults, agentBusy = false }: { open: boolean; receiving: boolean; sessionId: string | null; onViewResults: () => void; agentBusy?: boolean }) {
  const [started, setStarted] = useState(false);
  const [error, setError] = useState("");
  const runtime = useAbstreetRuntime();
  const sceneConfig = abstreetScenarios.find(item => item.id === runtime.scenarioId) ?? abstreetScenarios[0];
  const simulationUrl = abstreetUrl(sceneConfig);
  const [resourceRun, setResourceRun] = useState("");
  const pendingStart = useRef("");
  const switching = useRef(false);
  const city = sceneConfig.category === "urban";
  const viewer = useRef("");
  const pending = useRef("");
  const storedTask = useCongestionTask(sessionId);
  const storedMitigation = useMitigationTask(sessionId);
  const task = storedTask && abstreetRuntime.matches(storedTask) ? storedTask : null;
  const mitigation = storedMitigation && abstreetRuntime.matches(storedMitigation) ? storedMitigation : null;
  const mitigationBusy = !!mitigation && ["running","awaiting_selection","awaiting_decision","restoring"].includes(mitigation.status);
  const latestTask = mitigation && (mitigationBusy || !task || mitigation.startedAt >= task.startedAt) ? mitigation : task;
  const taskAutoFollow = useRef(true);
  const executor = useRef<MitigationExecutor | null>(null);
  const scenario = useRef<MitigationScenario | null>(null);
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
  const highwayOverview = useRef(true);
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
  const mitigationApproach = mitigation?.context?.approaches.find(a=>a.roadId===selectedRoad);
  const clockSeconds = mitigationBusy && !mitigation?.preset ? mitigation?.liveSignal?.simulationTime ?? simulation?.simulationTime : simulation?.simulationTime;
  const cameraParams = useRef((action: string, params: Record<string, unknown> = {}) => params);
  cameraParams.current = (action, params = {}) => {
    if (nativeUi || !["focus_on_road", "focus_on_intersection", "fit_roads", "global_view"].includes(action)) return params;
    const rect = viewport.current?.getBoundingClientRect();
    const iframe = viewport.current?.querySelector("iframe");
    if (!rect?.width || !iframe) return params;
    const ratio = iframe.clientWidth / rect.width;
    const top = Math.min((hud.current?.getBoundingClientRect().bottom ?? rect.top) - rect.top + 20, rect.height * .62);
    return { ...params, padding: { top: Math.max(0, top) * ratio, bottom: 56 * ratio, left: 20 * ratio, right: (["focus_on_road","focus_on_intersection"].includes(action) && rect.width > 620 ? 290 : 20) * ratio } };
  };
  const request = async (action: string, params: Record<string, unknown> = {}, signal?: AbortSignal) => {
    const doc = viewport.current?.querySelector("iframe")?.contentDocument;
    if (!doc) throw new Error("仿真尚未就绪，请等待加载。");
    return controlCurrentSimulation(doc, action, cameraParams.current(action, params), signal);
  };
  const rawRequest = useRef(request);
  const currentSession = useRef(sessionId);
  currentSession.current = sessionId;
  rawRequest.current = request;
  if (!executor.current) executor.current = new MitigationExecutor((action,params,signal)=>rawRequest.current(action,params,signal),async(roadIds,signal)=>{
    if(!taskAutoFollow.current)return;
    const task=mitigationStore.get(currentSession.current);
    const target=task?.targetRoadId??roadIds[0];
    const intersection=task?.context?.signal?task.context.intersectionId:undefined;
    await rawRequest.current(intersection!==undefined?"focus_on_intersection":roadIds.length>1?"fit_roads":"focus_on_road",{...(intersection!==undefined?{intersectionId:intersection}:roadIds.length>1?{roadIds}:{roadId:target}),smooth:!window.matchMedia("(prefers-reduced-motion: reduce)").matches},signal);
    setSelectedRoad(target);setFollowing(true);
  });
  if (!scenario.current) scenario.current = new MitigationScenario((action,params,signal)=>rawRequest.current(action,params,signal),async(roadIds,signal)=>{
    if (!taskAutoFollow.current) return;
    await rawRequest.current("focus_on_road", { roadId: roadIds[0], smooth: !window.matchMedia("(prefers-reduced-motion: reduce)").matches }, signal);
    setSelectedRoad(roadIds[0]); setFollowing(true);
  });
  const releaseMitigation = async () => {
    const previous = mitigationStore.get(sessionId);
    if (!previous || !["running","awaiting_selection","awaiting_decision","restoring"].includes(previous.status)) return;
    if (previous.preset) {
      await scenario.current?.cancel();
      mitigationStore.end(previous.sessionId,previous.id,"cancelled","已重新检测，上一项缓解任务已取消。");
    } else {
      await executor.current?.cancel("已重新检测，上一项配时任务已取消并恢复。");
      const current=mitigationStore.get(sessionId);
      if (current?.status === "failed" && current.message.includes("恢复失败")) throw new Error(current.message);
      if (current && !current.context && current.calls.every(call=>call.kind==="mcp")) mitigationStore.cancel(current.sessionId);
      if (mitigationStore.busy()) throw new Error("上一项配时任务尚未恢复，请先查看并取消该任务。");
    }
  };
  const cancelMitigation = () => {
    if (mitigation?.preset) void scenario.current?.cancel();
    else if (mitigationStore.recoveryRequired()) void executor.current?.cancel();
    else if (sessionId) mitigationStore.cancel(sessionId);
  };
  const releaseMitigationRef = useRef(releaseMitigation);
  releaseMitigationRef.current = releaseMitigation;
  useEffect(()=>{taskAutoFollow.current=true;},[mitigation?.id]);
  useEffect(()=>{
    const cancel=()=>{void scenario.current?.cancel();};
    window.addEventListener("pagehide",cancel);
    if (!receiving) cancel();
    return()=>{window.removeEventListener("pagehide",cancel);cancel();};
  },[sessionId,receiving]);
  useEffect(()=>{
    const cancel=(event:Event)=>{
      if((event as CustomEvent<{sessionId:string}>).detail.sessionId!==sessionId)return;
      if(mitigationStore.get(sessionId)?.preset)void scenario.current?.cancel();
      else void executor.current?.cancel();
    };
    window.addEventListener("traffic-cancel-mitigation",cancel);
    return()=>{window.removeEventListener("traffic-cancel-mitigation",cancel);void executor.current?.cancel("已离开当前会话，配时任务已取消并恢复。");};
  },[sessionId]);
  const chooseMitigation=async(choice:string)=>{
    if (mitigation?.preset) {
      try { await scenario.current!.choose(choice); }
      catch (error) { if (mitigationStore.get(sessionId)?.status !== "cancelled") throw error; }
      return;
    }
    if(!sessionId || !executor.current)throw new Error("当前会话不可用。");
    const authorization=executor.current.approve(sessionId,choice);
    const name=mitigation?.status==="awaiting_selection"?"evaluate_signal_plan":"finalize_signal_trial";
    if(!startMitigation(sessionId,undefined,`/skill:traffic-mitigation 用户已在面板${name==="evaluate_signal_plan"?"选择配时方案":"决定保留或恢复"}，请仅调用 ${name}，参数为 ${JSON.stringify(authorization)}。`))throw new Error("Agent 正忙，请等待当前回答结束后重新选择。");
    mitigationStore.panel(sessionId,true);
  };
  const interruptCamera = () => {
    highwayOverview.current = false;
    taskAutoFollow.current=false;
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
  const focusSignal = async () => {
    if(mitigation?.preset || !mitigation?.context?.signal) return;
    taskAutoFollow.current=true;setFollowing(true);
    await request("focus_on_intersection",{intersectionId:mitigation.context.intersectionId,smooth:!window.matchMedia("(prefers-reduced-motion: reduce)").matches});
  };
  const signalTaskId = mitigation?.id;
  const signalIntersection = mitigation?.context?.signal ? mitigation.context.intersectionId : undefined;
  const signalActive = !!mitigation && !mitigation.preset && mitigationBusy;
  useEffect(()=>{
    if(!open || !bridgeReady || !signalActive || signalIntersection===undefined || !sessionId || !signalTaskId)return;
    let stopped=false;
    const controller=new AbortController();
    let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try {
        const task=mitigationStore.get(sessionId);
        if(task?.id!==signalTaskId || !abstreetRuntime.matches(task))return;
        const signal=await rawRequest.current("get_signal_plan",{intersectionId:signalIntersection},controller.signal) as SignalPlan;
        if(stopped)return;
        await rawRequest.current("set_signal_visualization",{enabled:true,intersectionId:signalIntersection,previewStage:task.previewStage,leaseId:signalTaskId},controller.signal);
        if(!stopped)mitigationStore.update(sessionId,signalTaskId,{liveSignal:signal,signalError:undefined,signalReadAt:Date.now()});
      } catch(error) {
        if(!stopped) {
          mitigationStore.update(sessionId,signalTaskId,{liveSignal:null,signalError:`状态暂不可用：${String(error)}`});
          await rawRequest.current("set_signal_visualization",{enabled:false,leaseId:signalTaskId}).catch(()=>{});
        }
      } finally {if(!stopped)timer=setTimeout(poll,250);}
    };
    void poll();
    return()=>{stopped=true;clearTimeout(timer);controller.abort();void rawRequest.current("set_signal_visualization",{enabled:false,leaseId:signalTaskId}).catch(()=>{});};
  },[open,bridgeReady,signalActive,signalTaskId,signalIntersection,sessionId,runtime.runId]);
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
  useEffect(() => { setSelectedRoad(null); setAnchor(null); setViewResult(null); cameraVersion.current++; }, [sessionId]);
  useEffect(() => { setSelectedRoad(null); setViewResult(null); }, [task?.id]);
  const switchReason = (fromTool = false, reinitialize = false) => controlBusy || switching.current ? "仿真操作尚未完成，请稍后切换。" : runtime.status === "loading" ? "场景正在加载，请等待完成后再切换。" : scenarioSwitchReason({ mitigationBusy: reinitialize ? mitigationStore.busy() : mitigationStore.switchBlocked(), detectionBusy: congestionStore.busy(), agentBusy: !fromTool && agentBusy });
  const switchReasonRef = useRef(switchReason);
  switchReasonRef.current = switchReason;
  const loadScene = async (next: AbstreetScenario, fromTool = false, reinitialize = false) => {
    const reason = switchReasonRef.current(fromTool, reinitialize);
    if (reason) { setError(reason); return; }
    switching.current = true;
    try {
      active.current?.abort(); cameraVersion.current++;
      if (!fromTool && viewer.current) {
        const response = await fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "unregister", viewer: viewer.current, sessionId: sessionId ?? "", runId: runtime.runId }) });
        if (!response.ok) throw new Error("旧场景注销失败，请重试；当前状态尚未重新初始化。");
      }
      setResourceRun(""); setBridgeReady(false); setSimulation(null); setSelectedRoad(null); setAnchor(null); setViewResult(null); setNativeUi(false); setFollowing(true); setError("");
      ui.current = { nativeUi: false, roadId: null, supported: false };
      highwayOverview.current = true;
      pending.current = "";
      executor.current = null; scenario.current = null;
      if (reinitialize) mitigationStore.confirmReinitialize();
      abstreetRuntime.load(next.id);
    } finally { switching.current = false; }
  };
  const loadSceneRef = useRef(loadScene);
  loadSceneRef.current = loadScene;
  const selectScene = (next: AbstreetScenario) => {
    const reason = switchReason();
    if (reason) { setError(reason); return; }
    if (window.confirm("切换或重新加载场景后，当前场景进度将重置；对话与历史结果保留。是否继续？")) void loadScene(next).catch(error => setError(String(error)));
  };
  useEffect(() => { if (started && !abstreetRuntime.get().runId) abstreetRuntime.load(abstreetScenarios[0].id); }, [started]);
  useEffect(() => {
    if (!started || !runtime.runId) return;
    const controller = new AbortController();
    const timeout = setTimeout(() => { abstreetRuntime.update(runtime.runId, "failed", "场景加载超过 180 秒，请重试并检查地图、需求及控制桥。"); controller.abort(); }, 180000);
    void Promise.all([sceneConfig.mapPath, sceneConfig.demandPath].map(async path => {
      const response = await fetch(`/abstreet/data/${path.replace("../data/", "")}`, { method: "HEAD", signal: controller.signal });
      if (!response.ok) throw new Error(`场景资源读取失败（${response.status}）：${path}`);
    })).then(() => { if (!controller.signal.aborted) setResourceRun(runtime.runId); }).catch(error => {
      if (!controller.signal.aborted) abstreetRuntime.update(runtime.runId, "failed", String(error));
    }).finally(() => clearTimeout(timeout));
    return () => { controller.abort(); clearTimeout(timeout); };
  }, [started, runtime.runId, sceneConfig]);
  useEffect(() => {
    if (runtime.status !== "loading") return;
    const timeout = setTimeout(() => {
      if (abstreetRuntime.get().status === "loading") abstreetRuntime.update(runtime.runId, "failed", "场景加载超过 180 秒，控制桥未就绪，请重试。");
    }, 180000);
    return () => clearTimeout(timeout);
  }, [runtime.runId, runtime.status]);
  useEffect(() => {
    if (runtime.status !== "failed" || !pendingStart.current) return;
    const id = pendingStart.current;
    pending.current = id;
    void (async () => {
      await fetch(`/api/simulation-demo?viewer=${viewer.current}&sessionId=${encodeURIComponent(currentSession.current ?? "")}&scenarioId=${encodeURIComponent(runtime.scenarioId)}&runId=${runtime.runId}`);
      await fetch("/api/simulation-demo", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:"ack",id,viewer:viewer.current,scenarioId:runtime.scenarioId,runId:runtime.runId,ok:false,error:runtime.error})});
    })().catch(()=>{}).finally(()=>{ if (pendingStart.current === id) pendingStart.current = ""; });
  }, [runtime.status, runtime.error, runtime.scenarioId, runtime.runId]);
  useEffect(() => {
    const show = (event: Event) => setError(String((event as CustomEvent).detail));
    window.addEventListener("traffic-action-error", show);
    return () => window.removeEventListener("traffic-action-error", show);
  }, []);
  useEffect(() => {
    if (!started || !runtime.runId || resourceRun !== runtime.runId) return;
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
            if (!sceneIdentityMatches(sceneConfig, state)) throw new Error(`场景身份不匹配：期望 ${sceneConfig.mapPath} / ${sceneConfig.scene}，收到 ${state.map ?? "未知地图"} / ${state.scene ?? "未知需求"}。`);
            const supported = state.capabilities?.includes("traffic-pi-ui-v1") ?? false;
            if (!supported) throw new Error("控制桥版本不兼容，请重新加载。");
            ui.current.supported = supported;
            setSimulation(state);
            if (supported) await controlCurrentSimulation(doc, "set_native_ui", { enabled: ui.current.nativeUi }, controller.signal);
            if (sceneConfig.autoPlay) {
              const metrics = await controlCurrentSimulation(doc, "get_road_metrics", {}, controller.signal) as { roads: { roadId: number }[] };
              await controlCurrentSimulation(doc, "fit_roads", cameraParams.current("fit_roads", { roadIds: metrics.roads.map(road => road.roadId) }), controller.signal);
              await controlCurrentSimulation(doc, "set_speed", { speedMultiplier: 1 }, controller.signal);
              await controlCurrentSimulation(doc, "resume", {}, controller.signal);
            }
            controller.signal.throwIfAborted();
            attached = doc; setBridgeReady(supported);
            abstreetRuntime.update(runtime.runId, "ready");
            if (pendingStart.current) {
              const id = pendingStart.current; pending.current = id;
              await fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "ack", id, viewer: viewer.current, scenarioId: runtime.scenarioId, runId: runtime.runId, result: { ...state, scenarioId: runtime.scenarioId, runId: runtime.runId } }) });
              if (pendingStart.current === id) pendingStart.current = "";
            }
            let down: { x: number; y: number } | null = null;
            const stop = () => { highwayOverview.current=false; taskAutoFollow.current=false; cameraVersion.current++; setFollowing(false); if (supported) void controlCurrentSimulation(doc, "cancel_camera").catch(() => {}); };
            const pointerDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY }; };
            const pointerMove = (event: PointerEvent) => { if (down && Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) { down = null; stop(); } };
            const pointerUp = () => { down = null; };
            const key = (event: KeyboardEvent) => { if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "+", "-"].includes(event.key)) stop(); };
            doc.addEventListener("pointerdown", pointerDown, true); doc.addEventListener("pointermove", pointerMove, true); doc.addEventListener("pointerup", pointerUp, true); doc.addEventListener("wheel", stop, { passive: true, capture: true }); doc.addEventListener("keydown", key, true);
            cleanupInput = () => { doc.removeEventListener("pointerdown", pointerDown, true); doc.removeEventListener("pointermove", pointerMove, true); doc.removeEventListener("pointerup", pointerUp, true); doc.removeEventListener("wheel", stop, true); doc.removeEventListener("keydown", key, true); };
          }
          if (Date.now() - lastStateAt > 1500) {
            const state = await controlCurrentSimulation(doc, "get_simulation_state", {}, controller.signal) as SimulationState;
            if (!stopped) {
              setSimulation(state);
              if (!sceneIdentityMatches(sceneConfig, state)) {
                setBridgeReady(false);
                abstreetRuntime.update(runtime.runId, "failed", "仿真地图或需求已在原生界面中改变，请重新加载当前场景。");
                throw new Error("仿真地图或需求已改变，已停止接收当前场景命令。");
              }
              if (sceneConfig.endTime && state.simulationTime >= sceneConfig.endTime && (!state.paused || abstreetRuntime.get().status !== "ended")) {
                await controlCurrentSimulation(doc, "pause", {}, controller.signal);
                abstreetRuntime.update(runtime.runId, "ended");
              }
            }
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
      } catch (error) { if (!stopped) { setError(String(error)); if (!attached) abstreetRuntime.update(runtime.runId, "failed", String(error)); } }
      finally { if (!stopped) timer = setTimeout(() => { void sync(); }, 100); }
    }
    void sync();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); cleanupInput(); };
  }, [started, runtime.runId, runtime.scenarioId, resourceRun, sceneConfig]);
  useEffect(() => {
    if (!bridgeReady || city || !highwayOverview.current) return;
    const controller = new AbortController();
    void (async () => {
      const iframe = viewport.current?.querySelector("iframe");
      const deadline = Date.now() + 10000;
      while (iframe) {
        controller.signal.throwIfAborted();
        const view = await rawRequest.current("get_view_state", {}, controller.signal) as ViewState;
        if (Math.abs(view.width - iframe.clientWidth) < 2 && Math.abs(view.height - iframe.clientHeight) < 2) break;
        if (Date.now() > deadline) throw new Error("地图尺寸尚未更新，请点击全局重新适配。");
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      const value = await rawRequest.current("get_road_metrics", {}, controller.signal);
      const roads = (value as { roads: { roadId: number }[] }).roads;
      await rawRequest.current("fit_roads", { roadIds: roads.map(road => road.roadId) }, controller.signal);
    })().catch(error => { if (!controller.signal.aborted) setError(String(error)); });
    return () => controller.abort();
  }, [bridgeReady, city, size.width, size.height, safeTop, runtime.runId]);
  const control = async (action: string, params: Record<string, unknown> = {}) => {
    if (!bridgeReady || runtime.status === "loading" || runtime.status === "failed") { setError("场景尚未就绪，请等待加载或重试。"); return false; }
    if (runtime.status === "ended" && ["resume", "set_speed"].includes(action)) { setError("本轮演示已结束，请重新播放当前场景。"); return false; }
    setControlBusy(true);
    try {
      const data = await request(action, params);
      if (["pause", "resume", "set_speed"].includes(action)) setSimulation(data as SimulationState);
      setError("");
      return true;
    } catch (error) { setError(String(error)); }
    finally { setControlBusy(false); }
  };
  const startAnalysis = async () => {
    try {
      await releaseMitigation();
      if (!startCongestionAnalysis(sessionId)) setError("Agent 仍在执行或尚未准备好，请等待或停止当前任务后再开始。");
    } catch(error) {setError(String(error));}
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
    const receiver = viewer.current;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const unregister = (event?: Event) => {
      active.current?.abort();
      void executor.current?.cancel("接收窗口已关闭或切换会话，配时任务已取消并恢复。");
      if (sessionId) congestionStore.cancel(sessionId, "接收窗口已关闭或切换会话，检测已中止。");
      void fetch("/api/simulation-demo", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "unregister", viewer: receiver, sessionId: sessionId ?? "", scenarioId: runtime.scenarioId, runId: runtime.runId, handoff: event ? undefined : pendingStart.current }) }).catch(() => {});
    };
    let executingId = "";
    window.addEventListener("pagehide", unregister);
    async function execute(command: { id: string; action: string; params: Record<string, unknown>; sessionId?: string; toolCallId?: string; scenarioId?: string; runId?: string; createdAt: number }) {
      executingId = command.id;
      const controller = new AbortController();
      active.current = controller;
      const signal = controller.signal;
      const detection = command.action === "detect_congestion";
      const mitigationCommand = (mitigationTools as readonly string[]).includes(command.action);
      const cameraStart = cameraVersion.current;
      let ok = false;
      let result: unknown;
      let message = "";
      const deadline = setTimeout(() => controller.abort(new Error("浏览器执行超时。")), mitigationCommand ? command.action === "evaluate_signal_plan" ? 1250000 : 600000 : detection ? Math.max(1, command.createdAt + 300000 - Date.now()) : 65000);
      try {
        signal.throwIfAborted();
        if (!abstreetRuntime.matches(command)) throw new Error("请求属于已离开的场景或旧运行批次，请重新操作。");
        const capabilityError = scenarioActionReason(runtime.scenarioId, command.action);
        if (capabilityError) throw new Error(capabilityError);
        if (abstreetRuntime.get().status === "ended" && ["resume", "faster", "run_for", "run_until"].includes(command.action)) throw new Error("本轮高速演示已结束，请重新播放当前场景。");
        if (mitigationStore.recoveryRequired()) throw new Error("恢复未确认，请核查或明确重新初始化场景后再执行。");
        if (detection) {
          if (!sessionId || command.sessionId !== sessionId || !command.toolCallId) throw new Error("检测请求会话不匹配。");
          await releaseMitigationRef.current();
          signal.throwIfAborted();
          const currentTask = congestionStore.get(sessionId);
          if (currentTask?.id !== command.toolCallId && !congestionStore.start(sessionId, command.toolCallId)) throw new Error("已有其他任务正在执行，请先完成或取消。");
          congestionStore.scope(sessionId, command.toolCallId, runtime.scenarioId, runtime.runId);
          if (congestionStore.get(sessionId)?.status !== "running") throw new Error("检测请求已结束或取消，请重新发起检测。");
        }
        if (mitigationCommand && (!sessionId || command.sessionId !== sessionId)) throw new Error("配时任务会话不匹配。");
        if (detection || mitigationCommand) {
          setError("");
          while (abstreetRuntime.get().status !== "ready") {
            signal.throwIfAborted();
            if (abstreetRuntime.get().status === "failed") throw new Error(abstreetRuntime.get().error);
            if (Date.now() - command.createdAt >= 180000) throw new Error("准备画面超过 180 秒：A/B Street 接口尚未就绪，请检查场景加载。");
            await new Promise(resolve => setTimeout(resolve, 250));
          }
        }
        const doc = viewport.current?.querySelector("iframe")?.contentDocument;
        if (!doc) throw new Error("当前仿真尚未加载。");
        const request = async (action: string, params?: Record<string, unknown>) => {
          if (!abstreetRuntime.matches(command)) throw new Error("运行批次已更换。");
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
        const detectionResult = congestionStore.get(sessionId)?.result;
        const linkedSource = command.action === "analyze_congestion_cause" ? mitigationStore.takeSource(sessionId!) : undefined;
        result = command.action === "analyze_congestion_cause" && (command.params.presetScenario === true)
          ? await scenario.current!.start(sessionId!, linkedSource?.roadId ?? command.params.roadId as number|undefined, command.toolCallId!, signal,
              linkedSource?.result ?? congestionStore.get(sessionId)?.result)
          : mitigationCommand ? await executor.current!.execute(command.action,command.params,sessionId!,command.toolCallId!,signal,linkedSource?.result ?? (detectionResult && abstreetRuntime.matches(detectionResult) ? detectionResult : undefined)) : detection ? await executeCongestion(request, (stage, text) => {
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
        if (!abstreetRuntime.matches(command)) throw new Error("运行批次已更换，已忽略旧结果。");
        if (result && typeof result === "object") result = { ...result, scenarioId: runtime.scenarioId, runId: runtime.runId };
        setError(""); ok = true;
      } catch (error) { message = error instanceof Error ? error.message : String(error); if (!stopped) setError(message); }
      finally { clearTimeout(deadline); executingId = ""; }
      if (stopped || signal.aborted) {
        if (detection && sessionId) congestionStore.cancel(sessionId, message || "检测已中止。");
        return;
      }
      try {
        const response = await fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "ack", id: command.id, viewer: receiver, scenarioId: runtime.scenarioId, runId: runtime.runId, ok, result, error: message }) });
        if (!response.ok) throw new Error("检测确认失败或请求已过期，请重新检测。");
        if (detection) {
          if (ok) {
            congestionStore.result(sessionId!, command.toolCallId!, result as CongestionResult);
            congestionStore.progress(sessionId!, command.toolCallId!, 4, "地图标注完成，正在确认工具结果…");
          } else congestionStore.finish(sessionId!, command.toolCallId!, message);
        }
      } catch (error) {
        if (detection) congestionStore.finish(sessionId!, command.toolCallId!, String(error));
        if (mitigationCommand) {
          if (mitigationStore.get(sessionId)?.preset) await scenario.current?.cancel();
          else await executor.current?.cancel("任务结果确认失败，已取消并恢复任务起点。");
        }
      }
    }
    async function poll() {
      try {
        if (document.visibilityState === "visible" || (sessionId && congestionStore.get(sessionId)?.status === "running") || mitigationStore.busy()) {
          const response = await fetch(`/api/simulation-demo?viewer=${receiver}&sessionId=${encodeURIComponent(sessionId ?? "")}&scenarioId=${encodeURIComponent(runtime.scenarioId)}&runId=${runtime.runId}`);
          if (response.ok) {
            const { command } = await response.json();
            if (!command && executingId) active.current?.abort(new Error("请求已取消或接收租约已失效。"));
            if (!stopped && command && pending.current !== command.id && pendingStart.current !== command.id) {
              pending.current = command.id;
              if (command.action === "start") {
                const reason = switchReasonRef.current(true);
                if (reason || !window.confirm("重新加载城市交通？当前场景进度将重置。")) {
                  void fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "ack", id: command.id, viewer: receiver, scenarioId: runtime.scenarioId, runId: runtime.runId, ok: false, error: reason || "用户取消了场景重置。" }) });
                } else { pendingStart.current = command.id; void loadSceneRef.current(abstreetScenarios[0], true); }
              }
              else void execute(command);
            }
          }
        }
      } finally { if (!stopped) timer = setTimeout(() => { void poll().catch(() => {}); }, 1000); }
    }
    void poll().catch(() => {});
    return () => { stopped = true; clearTimeout(timer); window.removeEventListener("pagehide", unregister); unregister(); };
  }, [receiving, started, sessionId, runtime.runId, runtime.scenarioId]);
  useEffect(() => {
    const focusRoad = (event: Event) => {
      const detail = (event as CustomEvent<{ sessionId: string; roadId: number; result?: CongestionResult }>).detail;
      if (detail.sessionId !== sessionId) return;
      if (!detail.result || !abstreetRuntime.matches(detail.result)) { setError("该道路结果属于其他场景或旧批次，请在当前场景重新检测。"); return; }
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
  }, [sessionId, task?.status, runtime.runId]);
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
  useEffect(() => { if (open) setStarted(true); }, [open]);

  return <>
    <section inert={!open} aria-hidden={!open} className={styles.workspace} aria-label="交通仿真工作台">
      <div className={styles.scenarioBar}>
        <div className={styles.scenarioSwitch} role="group" aria-label="交通场景切换">{abstreetScenarios.map(item => <button key={item.id} type="button" aria-pressed={runtime.scenarioId === item.id} disabled={runtime.status === "loading"} onClick={() => { if (item.id !== runtime.scenarioId) selectScene(item); }}><span aria-hidden="true">{item.category === "urban" ? "▦" : "⇄"}</span>{item.label}</button>)}</div>
        <div><strong>{sceneConfig.name}</strong><span role="status">{runtime.status === "ready" ? simulation?.paused ? "已暂停" : "运行中" : runtime.status === "ended" ? "本轮演示已结束" : runtime.status === "failed" ? "加载失败" : "正在加载地图与车辆需求…"} · 批次 {runtime.runId.slice(0,8) || "准备中"}</span></div>
        <button type="button" disabled={runtime.status === "loading"} onClick={() => selectScene(sceneConfig)}>{runtime.status === "ended" ? "重新播放当前场景" : "重新加载"}</button>
      </div>
      {mitigationStore.switchBlocked() && <div className={styles.error} role="status"><span>{mitigationStore.recoveryRequired() ? "恢复未确认：继续执行与场景切换已锁定。重新初始化会丢弃当前状态，不等同于恢复。" : "当前任务未结束，请先完成或取消；恢复完成后才能切换场景。"}</span><button type="button" onClick={() => { if (sessionId) mitigationStore.panel(sessionId, true);if(!mitigation?.preset)onViewResults(); }}>返回当前任务</button><button type="button" onClick={cancelMitigation}>取消任务</button>{mitigationStore.recoveryRequired() && <button type="button" disabled={agentBusy || controlBusy || runtime.status === "loading"} onClick={() => { if (window.confirm("无法确认原状态已恢复。是否丢弃当前状态并重新初始化本场景？这不是恢复原状态。")) void loadSceneRef.current(sceneConfig, false, true).catch(error=>setError(String(error))); }}>重新初始化</button>}</div>}
      {error && <div className={styles.error} role="alert"><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="关闭提示">×</button></div>}
      <div ref={viewport} className={styles.viewport}>
        {runtime.status === "failed" && <div className={styles.loadNotice} role="alert"><strong>场景加载失败</strong><p>{runtime.error}</p><button type="button" onClick={() => selectScene(sceneConfig)}>重试</button><button type="button" onClick={() => selectScene(abstreetScenarios[0])}>重新加载城市交通</button></div>}
        {runtime.status === "loading" && <div className={styles.loading} role="status">正在加载{sceneConfig.name}，等待地图、需求与控制桥确认…</div>}
        {started && !!runtime.runId && resourceRun === runtime.runId && runtime.status !== "failed" && <iframe key={runtime.runId} title="本地交通仿真" src={simulationUrl} allow="fullscreen" style={{ width: size.width / scale, height: size.height / scale, transform: `scale(${scale})`, transformOrigin: "top left" }} />}
        {!nativeUi && <>
          <div ref={hud} className={styles.mapHud}>
          <section className={styles.sceneControls} aria-label="场景与时间控制">
            <small>A/B Street · 本地仿真实例</small><strong>{sceneConfig.name}</strong>
            <div className={styles.clock}><time>{clockSeconds!==undefined ? new Date(clockSeconds * 1000).toISOString().slice(11, 19) : "--:--:--"}</time><span>{mitigation?.observationPaused ? "已暂停观察" : simulation ? simulation.busy ? "任务推进中 · 5×" : simulation.paused ? "已暂停" : "运行中" : "场景加载中"}</span></div>
            <div className={styles.controlRow}><button type="button" disabled={!bridgeReady || controlBusy || mitigationBusy} onClick={() => void control(simulation?.paused ? "resume" : "pause")}>{simulation?.paused ? "▶ 继续" : "Ⅱ 暂停"}</button>
              <label>速度<select aria-label="仿真速度" disabled={!bridgeReady || controlBusy || mitigationBusy} value={simulation?.speedMultiplier ?? 1} onChange={event => void control("set_speed", { speedMultiplier: Number(event.target.value) })}>{[1,5,30,3600].map(speed => <option key={speed} value={speed}>{speed}×</option>)}</select></label></div>
            <small>{bridgeReady ? "控制已就绪" : "等待仿真接口就绪"}</small>
          </section>
          {city ? <TrafficWorkflow task={latestTask} onStart={startAnalysis} onView={()=>{if(sessionId)mitigationStore.panel(sessionId,true);if(!mitigation?.preset)onViewResults();}} onCancel={latestTask === mitigation ? cancelMitigation : () => { if (sessionId) congestionStore.cancel(sessionId, "用户已取消检测。"); }} /> : <section className={styles.sceneControls} aria-label="高速演示说明"><small>典型高速演示 · 合成路网与需求</small><strong>双向三车道 · 匝道汇入与驶出</strong><p>车辆由 A/B Street 实际运行。08:00 起以 1× 播放，需求持续至 08:32；不提供城市信号优化。</p></section>}
          <section className={styles.overview} aria-label="当前任务概览">{!city ? <><small>高速运行概览</small><strong>{runtime.status === "ended" ? "本轮演示已结束" : simulation?.paused ? "已暂停" : bridgeReady ? "车辆运行中" : "准备高速场景"}</strong><span>主线直行 · 匝道汇入 · 驶出</span><span>固定需求 · 种子 42</span><small>本轮 {runtime.runId.slice(0,8)}</small></> : <><small>当前任务概览</small>{latestTask===mitigation && mitigation ? <><strong>{mitigation.round??"拥堵溯源与配时"}</strong><span>目标道路 {mitigation.targetRoadId??"待确定"} · 路口 {mitigation.context?.intersectionId??"待确定"}</span><span>{mitigation.preset?mitigation.message:!mitigationBusy?"本轮采集已结束":mitigation.signalError??(mitigation.liveSignal?`相位 ${mitigation.liveSignal.currentStage+1} · 剩余 ${mitigation.liveSignal.stageRemainingSeconds?.toFixed(1)??"未提供"}s`:"等待信号状态")}</span>{!mitigation.preset && mitigation.planApplied && <small>新方案已生效 · 已核对</small>}{mitigation.observations.at(-1) && <span>{mitigation.preset?"模型排队":"当前排队"} {mitigation.observations.at(-1)?.approaches.find(a=>a.roadId===mitigation.targetRoadId)?.queueVehicles??"未提供"} 辆 · {!mitigation.preset && mitigation.round && `${mitigation.round}通过 ${Math.max(0,(mitigation.observations.at(-1)?.approaches.find(a=>a.roadId===mitigation.targetRoadId)?.passedVehicles??0)-(mitigation.observations[0]?.approaches.find(a=>a.roadId===mitigation.targetRoadId)?.passedVehicles??0))} 辆 · `}{mitigation.preset?"模型时刻":"采样"} {mitigation.observations.at(-1)!.simulationTime.toFixed(0)}s</span>}<button type="button" onClick={()=>{if(sessionId)mitigationStore.panel(sessionId,true);if(!mitigation?.preset)onViewResults();}}>查看信控详情</button><button type="button" disabled={!mitigation.targetRoadId} onClick={()=>{taskAutoFollow.current=true;setFollowing(true);void (mitigation.preset?focus(mitigation.targetRoadId!):focusSignal()).catch(error=>setError(String(error)));}}>定位目标道路</button></> : <><strong>{result ? `${result.roads.length} 处疑似拥堵` : task?.status === "running" ? "正在采集与分析" : "暂无检测结果"}</strong>
            {result ? <><span>道路 {roadIndex >= 0 ? roadIndex + 1 : "—"} / {result.roads.length} · 样本 {result.sampledRoadCount} 条</span><small>采集于 {new Date(result.metricsCollectedAt).toLocaleTimeString()}</small>{viewResult && viewResult.metricsCollectedAt !== task?.result?.metricsCollectedAt && <button type="button" onClick={() => { setViewResult(null); setSelectedRoad(null); }}>历史检测 · 返回最新</button>}{!result.roads.length && <span>当前未发现符合筛选条件的道路</span>}{result.roads.length > 0 && <button type="button" onClick={() => { setFollowing(true); void focus(road?.roadId ?? result.roads[0].roadId).catch(error => setError(String(error))); }}>定位当前道路</button>}</> : <span>通过对话或技能卡片开始分析</span>}
            {result && <div className={styles.overviewActions}><button type="button" onClick={onViewResults}>查看分析结果</button></div>}</>}
          </>}</section>
          </div>
          {latestTask===mitigation && mitigationApproach && anchor ? <ObjectDetails label="溯源道路详情" title={mitigationApproach.name && mitigationApproach.name!=="???"?mitigationApproach.name:`道路 ${mitigationApproach.roadId}`} subtitle={`道路 ${mitigationApproach.roadId} → 路口 ${mitigationApproach.toIntersectionId}`} anchor={{x:anchor.x*size.width,y:anchor.y*size.height}} bounds={size} safeTop={safeTop} onClose={()=>setSelectedRoad(null)}>
            <p>{mitigation?.preset?"推演排队":"采集排队"} {mitigationApproach.queueVehicles} 辆 · 路口等待 {mitigationApproach.waitingAtIntersection} 辆</p>
            <p>当前累计等待 {mitigationApproach.currentWaitingSeconds.toFixed(1)} 车辆秒 · 下游最大占用 {(mitigationApproach.downstreamOccupancy*100).toFixed(0)}%</p>
            <p>{mitigation?.preset?"模型时刻":"采集仿真时刻"} {mitigation!.context!.simulationTime.toFixed(0)} 秒</p><p>{mitigation!.evidence || mitigation!.message}</p>
            <button type="button" onClick={()=>{if(sessionId)mitigationStore.panel(sessionId,true);if(!mitigation?.preset)onViewResults();}}>查看溯源与方案</button>
          </ObjectDetails> : road && anchor && <ObjectDetails label="道路详情" title={road.name && road.name !== "???" ? road.name : `道路 ${road.roadId}`} subtitle={`道路 ${road.roadId} · ${roadIndex + 1} / ${result!.roads.length}`} anchor={{ x: anchor.x * size.width, y: anchor.y * size.height }} bounds={size} safeTop={safeTop} onClose={() => setSelectedRoad(null)}>
            <span className={styles.severity} data-level={road.level}>{road.level === "critical" ? "红色" : road.level === "severe" ? "橙色" : "黄色"} · 疑似拥堵</span>
            <dl><div><dt>排队车辆</dt><dd>{road.queueVehicles} 辆</dd></div><div><dt>平均车速</dt><dd>{road.meanVehicleSpeedKph.toFixed(1)} km/h</dd></div><div><dt>平均累计延误</dt><dd>{Number.isFinite(road.meanVehicleDelaySeconds) ? `${road.meanVehicleDelaySeconds!.toFixed(1)} 秒` : "未提供"}</dd></div><div><dt>车辆流量</dt><dd>{Number.isFinite((road as {flowVehiclesPerHour?: number}).flowVehiclesPerHour) ? `${(road as {flowVehiclesPerHour?: number}).flowVehiclesPerHour} 辆/小时` : "未提供"}</dd></div></dl>
            <small>采集于 {new Date(result!.metricsCollectedAt).toLocaleTimeString()} · 历史行程平均车速，非瞬时测速 · 接口样本 {result!.sampledRoadCount} 条道路</small>
            <button type="button" disabled={mitigationBusy || task?.status==="running"} onClick={()=>{if(!startMitigation(sessionId,road.roadId,undefined,result))setError("Agent 正忙，请等待当前任务结束后重试。");}}>分析缓解方案</button>
            <details><summary>其他方式</summary><small>预设参数模型；不修改真实配时。</small><button type="button" disabled={mitigationBusy || task?.status==="running"} onClick={()=>{if(!startMitigation(sessionId,road.roadId,undefined,result,true))setError("Agent 正忙，请等待后重试。");}}>预设模型推演</button></details>
            <div className={styles.roadNavigation}><button type="button" disabled={roadIndex <= 0 || task?.status === "running"} onClick={() => { setFollowing(true); void focus(result!.roads[roadIndex - 1].roadId).catch(error => setError(String(error))); }}>← 上一处</button><button type="button" disabled={roadIndex >= result!.roads.length - 1 || task?.status === "running"} onClick={() => { setFollowing(true); void focus(result!.roads[roadIndex + 1].roadId).catch(error => setError(String(error))); }}>下一处 →</button></div>
          </ObjectDetails>}
        </>}
        {open && mitigation && <MitigationPanel agentBusy={agentBusy} task={mitigation} targets={mitigation.preset?undefined:result?.roads.map(r=>({roadId:r.roadId,name:r.name}))} onTarget={async roadId=>{
          await executor.current?.cancel("已改选目标，旧候选已作废并恢复任务起点。");
          if (mitigationStore.recoveryRequired()) throw new Error("恢复未确认，不能更换目标。");
          if(!startMitigation(sessionId,roadId,undefined,mitigation.sourceDetection ?? result,mitigation.preset === true))throw new Error("Agent 正忙，请等待回答结束后重新选择目标。");
        }} onPreview={stage=>{
          if(!sessionId || mitigation.preset || !mitigationBusy || !mitigation.context?.signal)return;
          mitigationStore.update(sessionId,mitigation.id,{previewStage:stage});
          void request("set_signal_visualization",{enabled:true,intersectionId:mitigation.context.intersectionId,previewStage:stage,leaseId:mitigation.id}).catch(error=>setError(String(error)));
          const road=stage===undefined?undefined:mitigation.originalPlan?.stages[stage]?.movements.find(movement=>!movement.crosswalk)?.fromRoadId;
          if(road!==undefined){interruptCamera();void focus(road).catch(error=>setError(String(error)));}
        }} onFocus={roadId=>{interruptCamera();void focus(roadId).catch(error=>setError(String(error)));}} onPause={()=>{
          if(sessionId)mitigationStore.update(sessionId,mitigation.id,{pauseRequested:!mitigation.pauseRequested});
        }} onClose={()=>sessionId&&mitigationStore.panel(sessionId,false)} onChoose={chooseMitigation} onCancel={cancelMitigation} />}
        <div className={styles.viewActions} aria-label="地图操作">
          {nativeUi ? <button type="button" onClick={() => { void control("set_native_ui", { enabled: false }).then(ok => { if (ok) setNativeUi(false); }); }}>返回统一界面</button> : <>
            <button type="button" disabled={!bridgeReady} onClick={() => { interruptCamera(); void control("zoom_view", { factor: 1.4 }); }} aria-label="放大地图">＋</button>
            <button type="button" disabled={!bridgeReady} onClick={() => { interruptCamera(); void control("zoom_view", { factor: 1 / 1.4 }); }} aria-label="缩小地图">−</button>
            <button type="button" disabled={!bridgeReady} onClick={() => { interruptCamera(); highwayOverview.current = true; void (async () => {
              if (city) await control("global_view", { smooth: !window.matchMedia("(prefers-reduced-motion: reduce)").matches });
              else try { const data = await request("get_road_metrics") as {roads:{roadId:number}[]}; await control("fit_roads", {roadIds:data.roads.map(road=>road.roadId)}); } catch(error) {setError(String(error));}
            })(); }}>全局</button>
            <button type="button" aria-pressed={following} disabled={!bridgeReady || (!result?.roads.length && !mitigation?.targetRoadId)} onClick={() => { taskAutoFollow.current=true; setFollowing(true); void (latestTask===mitigation && mitigation?.context?.signal && !mitigation.preset ? focusSignal() : focus(latestTask===mitigation && mitigation?.targetRoadId!==undefined ? mitigation.targetRoadId : road?.roadId ?? result!.roads[0].roadId)).catch(error => setError(String(error))); }}>跟随任务</button>
          </>}
        </div>
        <div className={styles.moreActions}>
          {!nativeUi && <button type="button" disabled={!bridgeReady || mitigationBusy} onClick={async () => { try { await request("set_native_ui", { enabled: true }); setNativeUi(true); setError(""); } catch (error) { setError(String(error)); } }}>更多 · 原生界面</button>}
          <a href={abstreetUrl(sceneConfig, true)} target="_blank" rel="noopener noreferrer">独立打开</a>
          <button type="button" onClick={async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); } catch { setError("当前浏览器无法切换全屏，可使用独立打开。"); } }}>切换全屏</button>
        </div>
      </div>
      <footer className={styles.footer}><span>{city ? congestionRule : "Traffic Pi 合成路网与需求 · A/B Street v0.3.49 · 车辆供给至 08:32"}</span><span>共享本地实例 · 收起不暂停</span></footer>
    </section>
  </>;
}
