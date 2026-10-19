"""Shared, transport-independent entry point for the embedded UI and MCP."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from uuid import uuid4

from filelock import FileLock, Timeout
from simtrend_app.mcp_tools import SimTrendMCPService
from simtrend_app.map_selector import load_map_objects, build_spatial_context
from simtrend_app.structured_tasks import build_incident_task, build_demand_adjustment_task

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / ".runtime" / "jobs"
TOOLS = {
    "list_simtrend_scenarios": ("list_scenarios", "场景列表"),
    "get_simtrend_capabilities": ("get_capabilities", "场景能力"),
    "query_network_knowledge": ("query_network_knowledge", "路网信息查询"),
    "query_signal_control": ("query_signal_control", "信号控制与相位查询"),
    "run_incident_signal_optimization": ("run_incident_signal_optimization", "事件处置与信号优化"),
    "run_demand_impact_evaluation": ("run_demand_impact_evaluation", "交通需求影响评估"),
    "evaluate_parameterized_signal_plan": ("evaluate_signal_plan", "参数化信号方案仿真"),
    "diagnose_simulation_result": ("diagnose_simulation_result", "仿真结果诊断"),
    "compare_simulation_runs": ("compare_simulation_runs", "两次仿真公平对比"),
}
SIMULATIONS = {
    "run_incident_signal_optimization", "run_demand_impact_evaluation",
    "evaluate_parameterized_signal_plan",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_file(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("无效的任务编号。")
    return JOBS / f"{job_id}.json"


def write_job(job: dict) -> None:
    JOBS.mkdir(parents=True, exist_ok=True)
    path = job_file(job["id"])
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def read_job(job_id: str) -> dict:
    path = job_file(job_id)
    if not path.is_file():
        raise ValueError("任务不存在。")
    job = json.loads(path.read_text(encoding="utf-8"))
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(job["created_at"])).total_seconds()
    abandoned = job["status"] == "queued" and age > 60
    if job["status"] == "running" and job.get("pid"):
        abandoned = not process_alive(job["pid"])
    if abandoned:
        job.update(status="failed", finished_at=now(), result={
            "ok": False, "status": "interrupted", "type": "simtrend-result", "job_id": job_id,
            "message": "任务进程未能启动或已中断。已有文件保留，请检查 Python 环境后重新提交。",
        })
        write_job(job)
    filter_job_artifacts(job)
    return job


def process_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied is not proof of exit.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def public_job(job: dict) -> dict:
    return {key: value for key, value in job.items() if key not in {"artifact_paths", "pid"}}


def map_data(scenario_id: str) -> dict:
    scenario = SimTrendMCPService()._resolve_scenario(scenario_id)
    # Show the actual network, not a cosmetically filtered subset.
    config = {**scenario.map_config, "display_filter": {"enabled": False}}
    edges, lanes = load_map_objects(scenario.path, config)
    edges = [edge for edge in edges if edge["edge_id"] in lanes]
    return {
        "ok": True, "scenario_id": scenario.id, "name": scenario.name,
        "synthetic": config.get("coordinate_system") == "sumo_xy",
        "center": list(reversed(config.get("center", [31.0, 118.0]))),
        "zoom": config.get("zoom", 14), "edges": edges, "lanes": lanes,
        "zones": config.get("pickup_zones", []),
    }


def spatial_context(scenario_id: str, selection: dict) -> str:
    data = map_data(scenario_id)
    edge_id = selection.get("edge_id", "")
    edge = next((row for row in data["edges"] if row["edge_id"] == edge_id), None)
    if not edge:
        raise ValueError("选中的道路不属于当前场景。")
    lanes = data["lanes"][edge_id]
    lane_id = selection.get("lane_id", "")
    if lane_id and lane_id not in {lane["lane_id"] for lane in lanes}:
        raise ValueError("选中的车道不属于当前道路。")
    name = edge["edge_name"] or f"道路 {edge_id}"
    context = build_spatial_context({
        "scenario_id": scenario_id, "edge_id": edge_id, "lane_id": lane_id,
        "display_name": name, "lane_ids": [lane["lane_id"] for lane in lanes],
    })
    return "\n".join(line for line in context.splitlines() if line.strip() != "- 地图车道ID：")


def prepare_form(body: dict) -> tuple[str, dict]:
    scenario_id = body["scenario_id"]
    scenario = SimTrendMCPService()._resolve_scenario(scenario_id)
    form = body["form"]
    if body["task"] == "incident":
        selection = body.get("selection") or {}
        if body.get("draft_mode"):
            from simtrend_app.incident_drafts import FIELD_LABELS, prepare_incident_draft
            fields = {key: form.get(key) for key in FIELD_LABELS if key not in {"edge_id", "lane_id"}}
            validated = prepare_incident_draft(scenario_id, {**fields, **selection})
            if not validated["ready"]:
                raise ValueError("草案尚未完整：" + "、".join(validated["missing_fields"]))
        context = spatial_context(scenario_id, selection)
        lane_count = len(map_data(scenario_id)["lanes"][selection["edge_id"]])
        if not 1 <= int(form.get("lane_closure_count", 1)) <= lane_count:
            raise ValueError("封闭车道数不能超过所选道路的车道数。")
        draft = build_incident_task(
            scenario_name=scenario.name,
            location_name=form.get("location_name") or selection.get("edge_id", ""),
            incident_type=form.get("incident_type", "追尾事故"),
            incident_duration_minutes=form.get("incident_duration_minutes", 10),
            lane_closure_count=form.get("lane_closure_count", 1),
            objective=form.get("objective", "优先缓解排队"),
            simulation_duration_seconds=form.get("duration_seconds", 600),
            spatial_selection=selection,
        )
        return "run_incident_signal_optimization", {
            "scenario_id": scenario_id, "incident_text": draft.prompt + "\n" + context,
            "duration_seconds": form.get("duration_seconds", 600),
        }
    if body["task"] == "demand":
        draft = build_demand_adjustment_task(
            scenario_name=scenario.name, target=form["target"],
            direction=form["direction"], percentage=form["percentage"],
            spatial_scope=form.get("spatial_scope", "整个场景"),
            simulation_duration_seconds=form.get("duration_seconds", 600),
        )
        return "run_demand_impact_evaluation", {
            "scenario_id": scenario_id, "request_text": draft.prompt,
            "duration_seconds": form.get("duration_seconds", 600),
        }
    raise ValueError("不支持的任务表单。")


def validate_call(tool: str, arguments: dict) -> None:
    if tool not in TOOLS or not isinstance(arguments, dict):
        raise ValueError("未知工具或无效参数。")
    function = getattr(SimTrendMCPService(), TOOLS[tool][0])
    inspect.signature(function).bind(**arguments)
    if arguments.get("scenario_id"):
        SimTrendMCPService()._resolve_scenario(arguments["scenario_id"])
    if tool == "compare_simulation_runs":
        # Do not let an external caller turn the comparison tool into a file reader.
        for field in ("reference", "candidate"):
            selector = arguments.get(field, field)
            if selector in {"reference", "candidate", "latest", "baseline", "optimized",
                            "reference_demand", "adjusted_demand", "parameterized"}:
                continue
            path = (ROOT / selector).resolve()
            scenario = SimTrendMCPService()._resolve_scenario(arguments["scenario_id"])
            if not path.is_relative_to(scenario.runtime().agent_runs_dir.resolve()):
                raise ValueError("对比结果文件必须位于当前场景的运行目录中。")


def create_job(tool: str, arguments: dict, session_id: str = "") -> dict:
    validate_call(tool, arguments)
    job = {"id": uuid4().hex, "tool": tool, "title": TOOLS[tool][1],
           "arguments": arguments, "session_id": str(session_id)[:200],
           "status": "queued", "created_at": now(), "steps": [], "artifacts": []}
    write_job(job)
    return job


def submit(tool: str, arguments: dict, session_id: str = "") -> dict:
    job = create_job(tool, arguments, session_id)
    try:
        subprocess.Popen(
            [sys.executable, str(ROOT / "web_bridge.py"), "--job", job["id"]],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as exc:
        job.update(status="failed", result={"ok": False, "message": str(exc)}, finished_at=now())
        write_job(job)
    return public_job(job)


def artifact_run_root(result: dict, allowed: Path) -> Path | None:
    data = result.get("data")
    for value in (result.get("run_root"), data.get("run_root") if isinstance(data, dict) else None):
        if not isinstance(value, str) or not value:
            continue
        path = (ROOT / value).resolve()
        if path != allowed and path.is_relative_to(allowed):
            return path
    return None


def filter_job_artifacts(job: dict) -> None:
    """Repair old manifests on read, keeping artifact IDs and URLs stable."""
    result = job.get("result")
    scenario_id = job.get("arguments", {}).get("scenario_id")
    if not isinstance(result, dict) or not scenario_id or not job.get("artifact_paths"):
        return
    allowed = SimTrendMCPService()._resolve_scenario(scenario_id).runtime().agent_runs_dir.resolve()
    run_root = artifact_run_root(result, allowed)
    if run_root is None:
        return
    paths = {key: value for key, value in job["artifact_paths"].items()
             if (ROOT / value).resolve().is_relative_to(run_root)}
    job["artifact_paths"] = paths
    job["artifacts"] = [item for item in job.get("artifacts", []) if item["id"] in paths]
    result["artifacts"] = job["artifacts"]


def collect_artifacts(result: dict, job: dict) -> None:
    scenario_id = job["arguments"].get("scenario_id")
    if not scenario_id:
        return
    scenario = SimTrendMCPService()._resolve_scenario(scenario_id)
    allowed = scenario.runtime().agent_runs_dir.resolve()
    run_root = artifact_run_root(result, allowed)
    paths: set[Path] = set()
    def visit(value: Any):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and len(value) < 1024 and "\n" not in value:
            try:
                path = (ROOT / value).resolve()
                if path.is_relative_to(allowed) and (run_root is None or path.is_relative_to(run_root)):
                    if path.is_file():
                        paths.add(path)
            except (OSError, ValueError):
                pass
    visit(result)
    # Expand only the explicit run directory, never runtime metadata directories.
    if run_root is not None and run_root.is_dir():
        for pattern in ("*.gif", "*.sumocfg", "*.json"):
            paths.update(path for path in run_root.rglob(pattern) if path.resolve().is_relative_to(run_root))
    job["artifacts"] = []
    job["artifact_paths"] = {}
    for path in sorted(paths):
        if not path.is_relative_to(allowed) or path.suffix not in {".gif", ".json", ".xml", ".sumocfg"}:
            continue
        artifact_id = str(len(job["artifacts"]))
        job["artifact_paths"][artifact_id] = path.relative_to(ROOT).as_posix()
        job["artifacts"].append({
            "id": artifact_id, "name": path.name,
            "label": path.relative_to(allowed).as_posix(),
            "kind": "replay" if path.suffix == ".gif" else "file",
            "url": f"/api/simtrend/artifacts/{job['id']}/{artifact_id}",
        })


def run_job(job_id: str) -> dict:
    job = read_job(job_id)
    job.update(status="running", pid=os.getpid(), started_at=now())
    write_job(job)
    service = SimTrendMCPService()
    def progress(step: dict):
        job["steps"].append(step)
        write_job(job)
    service.progress_callback = progress
    tool = job["tool"]
    try:
        lock = FileLock(str(ROOT / ".runtime" / "simulation.lock"), timeout=0) if tool in SIMULATIONS else nullcontext()
        with lock:
            result = getattr(service, TOOLS[tool][0])(**job["arguments"])
            collect_artifacts(result, job)
        job["status"] = "completed" if result.get("ok") else (
            "clarification_required" if result.get("status") == "clarification_required" else "failed")
    except Timeout:
        result = {"ok": False, "status": "busy", "message": "已有仿真正在运行，请稍后重试。"}
        job["status"] = "failed"
    except Exception as exc:
        result = {"ok": False, "status": "error", "message": service._redact_text(str(exc))}
        job["status"] = "failed"
    if isinstance(result.get("message"), str):
        result["message"] = result["message"].split("\n\n工具链日志：", 1)[0]
    result.update(type="simtrend-result", tool=tool, job_id=job_id, artifacts=job["artifacts"])
    job.update(result=result, finished_at=now())
    write_job(job)
    return result


def execute(tool: str, arguments: dict) -> dict:
    return run_job(create_job(tool, arguments)["id"])


class MCPFacade:
    def __getattr__(self, name: str):
        tool = next((key for key, (method, _) in TOOLS.items() if method == name), None)
        if not tool:
            raise AttributeError(name)
        signature = inspect.signature(getattr(SimTrendMCPService(), name))
        def call(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            return execute(tool, bound.arguments)
        return call


def bridge(body: dict) -> dict:
    action = body.get("action")
    if action == "incident_draft":
        from simtrend_app.incident_drafts import prepare_incident_draft
        return prepare_incident_draft(body["scenario_id"], body.get("fields", {}), body.get("base_revision", 0))
    if action == "scenarios":
        return SimTrendMCPService().list_scenarios()
    if action == "map":
        return map_data(body["scenario_id"])
    if action == "start":
        tool, arguments = prepare_form(body) if body.get("form") else (body["tool"], body.get("arguments", {}))
        return {"ok": True, "job": submit(tool, arguments, body.get("session_id", ""))}
    if action == "job":
        return {"ok": True, "job": public_job(read_job(body["job_id"]))}
    if action == "jobs":
        jobs = [read_job(path.stem) for path in JOBS.glob("*.json")]
        jobs = [job for job in jobs if job["session_id"] == body.get("session_id", "")]
        return {"ok": True, "jobs": [public_job(job) for job in sorted(jobs, key=lambda j: j["created_at"], reverse=True)[:30]]}
    if action == "artifact":
        job = read_job(body["job_id"])
        relative = job.get("artifact_paths", {}).get(str(body["artifact_id"]))
        if not relative:
            raise ValueError("结果文件不存在。")
        path = (ROOT / relative).resolve()
        if not path.is_relative_to((ROOT / "simtrend_scenarios").resolve()) or "outputs" not in path.parts or not path.is_file():
            raise ValueError("结果文件路径无效。")
        return {"ok": True, "path": str(path), "name": path.name}
    raise ValueError("未知请求。")
