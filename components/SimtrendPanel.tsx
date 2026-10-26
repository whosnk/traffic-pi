"use client";

import { useEffect, useState } from "react";
import { SimtrendMap } from "./SimtrendMap";
import { SimtrendResult } from "./SimtrendResult";
import { simtrendRequest, type SimtrendScenario, type SimtrendMapData, type SimtrendSelection, type SimtrendJob, type SimtrendResult as Result } from "@/lib/simtrend-types";
import { trafficResultStore, useTrafficResults } from "@/lib/traffic-results";
import { simtrendContextStore, useSimtrendContext } from "@/lib/simtrend-context";
import { emptyIncidentForm, incidentDraftIssues, type IncidentDraftResult } from "@/lib/simtrend-draft";
import "./simtrend.css";

const tools = {
  incident: "事件处置与信号优化", demand: "交通需求影响评估", signal: "参数化信号方案",
  diagnose: "仿真结果诊断", compare: "两次仿真公平对比",
};
const steps: Record<string, string> = {
  detect_incident: "识别事件", build_signal_plan: "生成信号方案", analyze_closure_impact: "检查封道可行性",
  run_baseline_simulation: "运行基线仿真与回放", run_optimized_simulation: "运行优化仿真与回放",
  compare_metrics: "对比指标", generate_report: "生成报告", prepare_demand_plan: "生成需求方案",
  run_reference_demand_simulation: "运行原始需求仿真", run_adjusted_demand_simulation: "运行调整需求仿真",
  compare_demand_impact: "对比需求影响", generate_demand_report: "生成需求报告",
};
const statusNames: Record<string, string> = { queued: "等待执行", running: "正在执行", completed: "已完成", failed: "执行失败", clarification_required: "需要补充信息" };

export function SimtrendPanel({ active, sessionId, contextKey, switchReason }: { active: boolean; sessionId: string | null; contextKey: string; switchReason: () => string }) {
  const [scenarios, setScenarios] = useState<SimtrendScenario[]>([]);
  const context = useSimtrendContext(contextKey);
  const scenarioId = context?.scenarioId ?? "";
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [visited, setVisited] = useState<string[]>([]);
  useEffect(() => {
    if (scenarioId) setVisited(ids => ids.includes(scenarioId) ? ids : [...ids, scenarioId]);
  }, [scenarioId]);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController();
    simtrendRequest<{ scenarios: SimtrendScenario[] }>({ action: "scenarios" }, abort.signal).then(data => {
      if (abort.signal.aborted) return;
      setScenarios(data.scenarios);
      const current = simtrendContextStore.get(contextKey);
      const selected = data.scenarios.find(item => item.scenario_id === current?.scenarioId) ?? data.scenarios[0];
      if (selected) simtrendContextStore.scene(contextKey, selected.scenario_id, selected.name);
      setError("");
    }).catch(error => { if (!abort.signal.aborted) setError(String(error.message)); });
    return () => abort.abort();
  }, [active, reload, contextKey]);
  const scenario = scenarios.find(item => item.scenario_id === scenarioId);
  return <div className="simtrend-panel">
    <header className="simtrend-header"><div><small>SIMTREND</small><h2>仿真实验 · SUMO</h2></div><button type="button" onClick={() => setReload(v => v + 1)}>刷新连接</button></header>
    {error && <p className="simtrend-error" role="alert">{error}</p>}
    <label className="simtrend-scene-label">仿真场景<select aria-label="仿真场景" value={scenarioId} onChange={event => { const item = scenarios.find(row => row.scenario_id === event.target.value); if (item) { const reason = switchReason(); if (reason) { setError(reason); return; } simtrendContextStore.scene(contextKey, item.scenario_id, item.name); setError(""); } }}>{scenarios.map(item => <option value={item.scenario_id} key={item.scenario_id}>{item.name}</option>)}</select></label>
    {!scenario && !error && <p role="status">正在加载场景…</p>}
    <p className="simtrend-description">当前引擎为 SUMO；主地图 A/B Street 与实验道路 ID 不通用。切换场景不取消后台 jobs；表单按场景保留，本次页面刷新后重置。运行环境由实际任务响应确认。</p>
    {scenarios.filter(item => item.scenario_id === scenarioId || visited.includes(item.scenario_id)).map(item => <div className="simtrend-scene-workspace" key={`${contextKey}:${item.scenario_id}`} hidden={item.scenario_id !== scenarioId} inert={item.scenario_id !== scenarioId}>
      <SceneWorkspace contextKey={contextKey} scenario={item} sessionId={sessionId} />
    </div>)}
  </div>;
}

function SceneWorkspace({ scenario, sessionId, contextKey }: { scenario: SimtrendScenario; sessionId: string | null; contextKey: string }) {
  const [map, setMap] = useState<SimtrendMapData | null>(null);
  const currentContext = useSimtrendContext(contextKey);
  const context = currentContext?.scenarioId === scenario.scenario_id ? currentContext : null;
  const selection = context?.scenarioId === scenario.scenario_id ? context.selection : null;
  function setSelection(value: SimtrendSelection) {
    const road = map?.edges.find(item => item.edge_id === value.edge_id);
    if (!road || !map) return;
    const laneIds = (map.lanes[value.edge_id] ?? []).map(lane => lane.lane_id);
    if (value.lane_id && !laneIds.includes(value.lane_id)) return;
    const pickup = map.zones.find(item => item.id === value.zone_id && item.edge_id === value.edge_id);
    if (value.zone_id && (!pickup || (value.lane_id && pickup.lane_id !== value.lane_id))) return;
    simtrendContextStore.select(contextKey, scenario.scenario_id, {
      ...value, label: pickup?.name || road.edge_name || "已选道路", laneIds,
    });
  }
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState(context?.incidentDraft?.id ? "tasks" : "map");
  const [task, setTask] = useState<keyof typeof tools>("incident");
  const [duration, setDuration] = useState(600);
  const incidentForm = context?.incidentDraft?.form ?? emptyIncidentForm();
  const editIncident = (patch: Partial<typeof incidentForm>) => simtrendContextStore.editIncident(contextKey, patch);
  const [target, setTarget] = useState(scenario.scenario_id.includes("nanjing") ? "网约车到站流量" : "全部流量");
  const [direction, setDirection] = useState("提高");
  const [percentage, setPercentage] = useState(30);
  const [scope, setScope] = useState("整个场景");
  const [controller, setController] = useState("");
  const [program, setProgram] = useState("0");
  const [phases, setPhases] = useState("");
  const [seed, setSeed] = useState(42);
  const [slot, setSlot] = useState("latest");
  const [variant, setVariant] = useState("latest");
  const [reference, setReference] = useState("reference");
  const [candidate, setCandidate] = useState("candidate");
  const [query, setQuery] = useState("");
  const [jobs, setJobs] = useState<SimtrendJob[]>([]);
  const [job, setJob] = useState<SimtrendJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const resultState = useTrafficResults(sessionId);
  const sceneId = scenario.scenario_id;
  const sid = sessionId ?? "simtrend-workspace";
  const busy = submitting || job?.status === "running" || job?.status === "queued";
  const edge = map?.edges.find(item => item.edge_id === selection?.edge_id);
  const lanes = edge ? map?.lanes[edge.edge_id] ?? [] : [];
  const zone = map?.zones.find(item => item.id === selection?.zone_id);
  const chatResults = resultState.results.filter(item => item.type === "simtrend" && (item.data as Result).scenario_id === sceneId);
  const resultSelection = (job?.result?.spatial_selection ?? job?.result?.data?.spatial_selection) as SimtrendSelection | undefined;
  const canLocate = resultSelection?.edge_id && map?.edges.some(item => item.edge_id === resultSelection.edge_id);
  const latestSteps = [...new Map((job?.steps ?? []).map(step => [step.tool, step])).values()];
  const incidentIssues = incidentDraftIssues(incidentForm, selection, lanes.length);
  const incomingDraftId = context?.incidentDraft?.id;
  useEffect(() => {
    if (incomingDraftId) { setTask("incident"); setTab("tasks"); }
  }, [incomingDraftId]);
  useEffect(() => {
    const abort = new AbortController();
    simtrendRequest<SimtrendMapData>({ action: "map", scenario_id: sceneId }, abort.signal).then(data => {
      if (abort.signal.aborted) return;
      setMap(data);
      const current = simtrendContextStore.get(contextKey);
      const selected = current?.scenarioId === sceneId ? current.selection : null;
      if (selected && (!data.edges.some(row => row.edge_id === selected.edge_id)
        || (selected.lane_id && !data.lanes[selected.edge_id]?.some(row => row.lane_id === selected.lane_id))
        || (selected.zone_id && !data.zones.some(row => row.id === selected.zone_id && row.edge_id === selected.edge_id)))) {
        simtrendContextStore.select(contextKey, sceneId, null);
      }
    }).catch(error => { if (!abort.signal.aborted) setError(error.message); });
    simtrendRequest<{ jobs: SimtrendJob[] }>({ action: "jobs", session_id: sid }, abort.signal).then(data => {
      const matching = data.jobs.filter(item => item.arguments.scenario_id === sceneId);
      setJobs(matching); setJob(matching[0] ?? null);
    }).catch(error => { if (!abort.signal.aborted) setError(error.message); });
    return () => abort.abort();
  }, [sceneId, sid, contextKey]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const data = await simtrendRequest<{ job: SimtrendJob }>({ action: "job", job_id: job.id }, abort.signal);
        if (abort.signal.aborted) return;
        setJob(data.job);
        setJobs(items => [data.job, ...items.filter(item => item.id !== data.job.id)]);
      } catch (error) {
        if (!abort.signal.aborted) setError((error as Error).message);
      }
      if (!abort.signal.aborted) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, 500);
    return () => { abort.abort(); clearTimeout(timer); };
  }, [job?.id, job?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!sessionId || !job?.result) return;
    trafficResultStore.add(sessionId, {
      id: `simtrend-${job.id}`, type: "simtrend", title: job.title, receivedAt: Date.now(),
      toolName: job.tool, data: job.result, unread: true,
    });
  }, [sessionId, job]);

  async function start(body: Record<string, unknown>) {
    setSubmitting(true); setError(""); setNotice("");
    try {
      const data = await simtrendRequest<{ job: SimtrendJob }>({ action: "start", session_id: sid, ...body });
      setJob(data.job); setJobs(items => [data.job, ...items]); setTab("results");
    } catch (error) { setError((error as Error).message); }
    finally { setSubmitting(false); }
  }
  function call(tool: string, args: Record<string, unknown>) {
    return start({ tool, arguments: { scenario_id: sceneId, ...args } });
  }
  async function submitTask() {
    if (task === "incident") {
      if (incidentIssues.length) { setError(incidentIssues.join("；")); return; }
      const revision = simtrendContextStore.get(contextKey)?.revision;
      setSubmitting(true); setError("");
      try {
        const validated = await simtrendRequest<IncidentDraftResult>({ action: "incident_draft", scenario_id: sceneId, fields: { ...incidentForm, edge_id: selection?.edge_id, lane_id: selection?.lane_id, zone_id: selection?.zone_id } });
        if (!validated.ready) throw new Error(validated.missing_fields.join("、"));
        if (simtrendContextStore.get(contextKey)?.revision !== revision) throw new Error("任务参数已变更，请检查当前草案后重新确认运行。");
        return await start({ task, scenario_id: sceneId, draft_mode: true, selection: validated.selection,
          form: { ...validated.form, location_name: validated.location_name } });
      } catch (error) { setError((error as Error).message); }
      finally { setSubmitting(false); }
      return;
    }
    if (task === "demand") return start({ task, scenario_id: sceneId, form: { target, direction, percentage, spatial_scope: scope, duration_seconds: duration } });
    if (task === "signal") {
      const values = phases.split(/[,，\s]+/).filter(Boolean).map(Number);
      if (!controller.trim() || !values.length || values.some(value => !Number.isFinite(value) || value <= 0)) { setError("请先查询控制器，填写其完整相位时长（正数，逗号分隔）。"); return; }
      return call("evaluate_parameterized_signal_plan", { controller_id: controller.trim(), program_id: program, phase_durations: values, duration_seconds: duration, random_seed: seed, render_animation: true, result_slot: slot });
    }
    if (task === "diagnose") return call("diagnose_simulation_result", { variant, top_n: 5 });
    return call("compare_simulation_runs", { reference, candidate, top_n: 5 });
  }
  async function openChatResult(result: Result) {
    try {
      const data = await simtrendRequest<{ job: SimtrendJob }>({ action: "job", job_id: result.job_id });
      setJob(data.job); setTab("results");
    } catch (error) { setError((error as Error).message); }
  }
  async function copyContext() {
    if (!edge) return;
    try {
      await navigator.clipboard.writeText(`当前场景：${sceneId}\n地图对象名称：${edge.edge_name || edge.edge_id}\n地图道路ID：${edge.edge_id}\n${selection?.lane_id ? "地图车道ID：" + selection.lane_id + "\n" : ""}地图道路全部车道：${lanes.map(lane => lane.lane_id).join(",")}\n请基于以上选定对象执行我的下一条请求。`);
      setNotice("已复制定位信息。左侧对话已自动关联当前定位，无需再粘贴。");
    } catch { setError("浏览器不允许复制，请手动复制道路和车道编号。"); }
  }
  return <>
    <p className="simtrend-description">{scenario.description}</p>
    <nav className="simtrend-tabs" aria-label="仿真面板"><button type="button" aria-pressed={tab === "map"} onClick={() => setTab("map")}>空间对象与查询</button><button type="button" aria-pressed={tab === "tasks"} onClick={() => setTab("tasks")}>创建仿真任务</button><button type="button" aria-pressed={tab === "results"} onClick={() => setTab("results")}>运行记录与回放{busy ? " · 执行中" : ""}</button></nav>
    {error && <p className="simtrend-error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {context?.draftNotice && <p className="simtrend-error" role="status">{context.draftNotice}</p>}
    {tab === "map" && <>
      {map ? <SimtrendMap data={map} selection={selection} onSelect={setSelection} /> : <p>正在加载仿真路网…</p>}
      <label>搜索道路名称或 ID<input aria-label="搜索道路" value={search} onChange={event => setSearch(event.target.value)} placeholder="例如：东北路口、e0_c10" /></label>
      {search && <div className="simtrend-road-search">{map?.edges.filter(item => (item.edge_id + item.edge_name).toLowerCase().includes(search.toLowerCase())).slice(0, 30).map(item => <button type="button" key={item.edge_id} onClick={() => { setSelection({ edge_id: item.edge_id }); setSearch(""); }}>{item.edge_name || "道路"} · {item.edge_id}</button>)}</div>}
      {edge ? <section className="simtrend-selection"><h3>{zone?.name || edge.edge_name || "已选道路"}</h3><code>{edge.edge_id}</code><p>行驶方向：{edge.from_node} → {edge.to_node}</p>
        {zone && <p>候选上客区容量：{zone.capacity} 辆 · 停靠等待：{zone.boarding_duration_s} 秒</p>}
        <div className="simtrend-lanes"><button type="button" aria-pressed={!selection?.lane_id} onClick={() => setSelection({ edge_id: edge.edge_id })}>整条道路</button>{lanes.map(lane => <button type="button" key={lane.lane_id} aria-pressed={selection?.lane_id === lane.lane_id} onClick={() => setSelection({ edge_id: edge.edge_id, lane_id: lane.lane_id })}><strong>车道 {lane.index}</strong><code>{lane.lane_id}</code><small>{lane.length_m} 米 · {(lane.speed_limit_mps * 3.6).toFixed(0)} km/h</small></button>)}</div>
        <div className="simtrend-actions"><button type="button" disabled={busy} onClick={() => call("query_network_knowledge", { query: `查询${selection?.lane_id ? "车道 " + selection.lane_id : "道路 " + edge.edge_id} 的详细信息` })}>已选对象详情</button><button type="button" disabled={busy} onClick={() => call("query_signal_control", { edge_id: edge.edge_id, lane_id: selection?.lane_id || "" })}>信号控制范围与相位</button><button type="button" onClick={() => { setTask("incident"); setTab("tasks"); }}>为此处创建事件任务</button><button type="button" onClick={copyContext}>复制定位到对话</button></div>
      </section> : <p>请点选地图道路、上客区，或搜索道路，再选择具体车道。</p>}
      <form className="simtrend-query" onSubmit={event => { event.preventDefault(); void call("query_network_knowledge", { query }); }}><label>路网信息查询<input value={query} onChange={event => setQuery(event.target.value)} placeholder="例如：这个场景有哪些路口？" required /></label><button disabled={busy} type="submit">查询</button></form>
      <button type="button" disabled={busy} onClick={() => call("query_signal_control", {})}>查询全部信号控制器</button>
    </>}
    {tab === "tasks" && <form className="simtrend-form" onSubmit={event => { event.preventDefault(); void submitTask(); }}>
      <label>任务类型<select value={task} onChange={event => setTask(event.target.value as keyof typeof tools)}>{Object.entries(tools).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      {task === "incident" && <>
        <section className="simtrend-draft" aria-label="事件任务草案">
          <strong>{context?.incidentDraft?.id ? "对话生成的任务草案" : "事件任务草案"}{context?.incidentDraft?.edited ? " · 已手动编辑" : ""}</strong>
          <p>当前场景：{scenario.name}</p>
          <p>事件位置：<strong>{edge ? (edge.edge_name || edge.edge_id) + (selection?.lane_id ? " / " + selection.lane_id : " / 待选择具体车道") : "请先在空间面板选择道路和车道"}</strong></p>
          <button type="button" onClick={() => setTab("map")}>在地图修改事故位置</button>
          <p>封闭从仿真第 0 秒开始{incidentForm.incident_duration_minutes != null ? `，持续至第 ${incidentForm.incident_duration_minutes * 60} 秒` : "，持续时间待补充"}。请核对参数后确认运行。</p>
          {incidentForm.duration_seconds != null && incidentForm.incident_duration_minutes != null && incidentForm.incident_duration_minutes * 60 > incidentForm.duration_seconds && <p>当前仿真时长短于事故持续时间，只能覆盖部分事故过程。</p>}
          {incidentIssues.length > 0 ? <ul>{incidentIssues.map(issue => <li key={issue}>{issue}</li>)}</ul> : <p>参数已齐全，等待确认运行。</p>}
        </section>
        <label>事件类型<select value={incidentForm.incident_type ?? ""} onChange={event => editIncident({ incident_type: event.target.value || null })} required><option value="">待补充</option>{["追尾事故", "碰撞事故", "车辆抛锚"].map(name => <option key={name}>{name}</option>)}</select></label>
        <label>持续时间（分钟）<input type="number" min="1" max="180" value={incidentForm.incident_duration_minutes ?? ""} onChange={event => editIncident({ incident_duration_minutes: event.target.value === "" ? null : +event.target.value })} required /></label>
        <label>封闭车道数<input type="number" min="1" max={Math.min(8, lanes.length || 8)} value={incidentForm.lane_closure_count ?? ""} onChange={event => editIncident({ lane_closure_count: event.target.value === "" ? null : +event.target.value })} required /></label>
        <label>优化目标<select value={incidentForm.objective ?? ""} onChange={event => editIncident({ objective: event.target.value || null })} required><option value="">待补充</option><option>优先缓解排队</option><option>优先降低等待时间</option></select></label>
        <small>沿用原项目启发式配时算法；结果用于仿真演示。</small>
      </>}
      {task === "demand" && <><label>调整对象<select value={target} onChange={event => setTarget(event.target.value)}>{(sceneId.includes("nanjing") ? ["网约车到站流量", "网约车离站流量", "全部网约车流量", "背景社会车辆流量", "全部流量"] : ["全部流量"]).map(name => <option key={name}>{name}</option>)}</select></label><label>调整方向<select value={direction} onChange={event => setDirection(event.target.value)}><option>提高</option><option>降低</option></select></label><label>调整幅度（%）<input type="number" min="1" max="100" value={percentage} onChange={event => setPercentage(+event.target.value)} required /></label><label>空间范围<select value={scope} onChange={event => setScope(event.target.value)}>{(sceneId.includes("nanjing") ? ["整个场景", "南京南站北广场", "南京南站南广场"] : ["整个场景"]).map(name => <option key={name}>{name}</option>)}</select></label></>}
      {task === "signal" && <><p>先查询控制器及相位，再按查询返回顺序填写完整时长，包括黄灯。</p><label>控制器 ID<input value={controller} onChange={event => setController(event.target.value)} placeholder="例如 c00" required /></label><label>程序 ID<input value={program} onChange={event => setProgram(event.target.value)} required /></label><label>完整相位时长（秒）<input value={phases} onChange={event => setPhases(event.target.value)} placeholder="例如 42, 3, 42, 3" required /></label><label>随机种子<input type="number" min="0" value={seed} onChange={event => setSeed(+event.target.value)} required /></label><label>保存为<select value={slot} onChange={event => setSlot(event.target.value)}><option value="latest">最近方案</option><option value="reference">基准方案</option><option value="candidate">候选方案</option></select></label></>}
      {task === "diagnose" && <label>诊断方案<select value={variant} onChange={event => setVariant(event.target.value)}>{["latest", "baseline", "optimized", "reference_demand", "adjusted_demand", "parameterized"].map(name => <option key={name}>{name}</option>)}</select></label>}
      {task === "compare" && <><p>对比前检查场景、仿真时长、随机种子和交通需求。先分别保存基准与候选方案。</p><label>基准结果<input value={reference} onChange={event => setReference(event.target.value)} required /></label><label>候选结果<input value={candidate} onChange={event => setCandidate(event.target.value)} required /></label></>}
      {["incident", "demand", "signal"].includes(task) && <label>仿真时长（秒）<input type="number" min="60" max="3600" value={task === "incident" ? incidentForm.duration_seconds ?? "" : duration} onChange={event => task === "incident" ? editIncident({ duration_seconds: event.target.value === "" ? null : +event.target.value }) : setDuration(+event.target.value)} required /></label>}
      <button className="simtrend-primary" type="submit" disabled={busy || (task === "incident" && (incidentIssues.length > 0 || !edge))}>{busy ? "任务执行中…" : task === "incident" ? "确认草案并运行仿真" : ["diagnose", "compare"].includes(task) ? "执行分析" : "创建并运行仿真"}</button>
    </form>}
    {tab === "results" && <section>
      {chatResults.length > 0 && <div className="simtrend-history"><strong>对话中的结果</strong>{chatResults.slice(0, 8).map(item => <button type="button" key={item.id} onClick={() => openChatResult(item.data as Result)}>{item.title}</button>)}</div>}
      <div className="simtrend-history">{jobs.map(item => <button type="button" aria-pressed={job?.id === item.id} key={item.id} onClick={() => setJob(item)}>{item.title} · {statusNames[item.status] || item.status}<small>{new Date(item.created_at).toLocaleString()}</small></button>)}</div>
      {!job && <p>暂无运行记录。查询和仿真结果将在这里显示。</p>}
      {job && <><h3>{job.title}</h3><p role="status">{statusNames[job.status] || job.status} · {job.id.slice(0, 8)}</p><ol className="simtrend-progress">{latestSteps.map(step => <li key={step.tool}>{steps[step.tool] || step.tool} · {statusNames[step.status] || step.status}</li>)}</ol>{canLocate && <button type="button" onClick={() => { setSelection(resultSelection!); setTab("map"); }}>在地图中定位结果对象</button>}{job.result && <SimtrendResult result={job.result} />}</>}
    </section>}
  </>;
}
