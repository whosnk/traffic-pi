from __future__ import annotations

import hashlib
from datetime import datetime
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from simtrend_app.config import Settings
from simtrend_app.edge_metrics import collect_edge_metrics
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.simulation_diagnostics import find_simulation_result
from simtrend_app.tool_scripts.common import collect_metrics, load_json, save_json
from simtrend_app.tools.base import ToolResult


SLOT_DIRS = {
    "reference": "parameterized_reference",
    "candidate": "parameterized_candidate",
    "latest": "parameterized_latest",
}

VARIANT_FILES = {
    "baseline": "baseline_result.json",
    "optimized": "optimized_result.json",
    "reference_demand": "reference_demand_result.json",
    "adjusted_demand": "adjusted_demand_result.json",
    "parameterized": "parameterized_result.json",
}

RUN_DIRS = {
    "baseline_result.json": "baseline",
    "optimized_result.json": "optimized",
    "reference_demand_result.json": "reference_demand",
    "adjusted_demand_result.json": "adjusted_demand",
    "parameterized_result.json": "simulation",
}


def compare_simulation_runs(
    settings: Settings,
    reference: str = "reference",
    candidate: str = "candidate",
    top_n: int = 5,
) -> ToolResult:
    runtime = ScenarioRuntime.from_project_dir(settings.sumo_project_dir)
    try:
        reference_file = resolve_simulation_result(runtime, reference)
        candidate_file = resolve_simulation_result(runtime, candidate)
        if reference_file.resolve() == candidate_file.resolve():
            raise ValueError("基准与候选指向同一个仿真结果，请选择两个不同结果。")
        comparison = build_fair_comparison(
            runtime,
            reference_file,
            candidate_file,
            top_n=max(1, min(int(top_n), 10)),
        )
        output_file = runtime.agent_runs_dir / ("comparison_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")) / "json" / "fair_comparison.json"
        save_json(output_file, comparison)
    except (FileNotFoundError, ValueError, ET.ParseError, OSError, json.JSONDecodeError) as exc:
        return ToolResult(
            ok=False,
            message=f"仿真结果公平对比失败：{exc}",
            data={
                "error": {
                    "code": "COMPARISON_INPUT_INVALID",
                    "message": str(exc),
                    "recoverable": True,
                }
            },
        )
    return ToolResult(
        ok=True,
        message=format_fair_comparison_markdown(comparison),
        data={
            "workflow_type": "fair_simulation_comparison",
            "comparison": comparison,
            "comparison_json": str(output_file),
            "spatial_selection": comparison.get("spatial_selection", {}),
        },
    )


def resolve_simulation_result(runtime: ScenarioRuntime, selector: str) -> Path:
    value = str(selector or "").strip()
    configured_path = Path(value)
    if value and configured_path.is_file():
        return configured_path.resolve()
    normalized = value.lower()
    if normalized in SLOT_DIRS:
        candidates = list(runtime.agent_runs_dir.glob(f"{SLOT_DIRS[normalized]}*/json/parameterized_result.json"))
        if candidates:
            return max(candidates, key=lambda item: item.stat().st_mtime)
        path = runtime.agent_runs_dir / SLOT_DIRS[normalized] / "json" / "parameterized_result.json"
        if path.exists():
            return path
        raise FileNotFoundError(f"结果槽 `{normalized}` 为空，请先运行并保存对应参数化仿真。")
    if normalized in VARIANT_FILES:
        return find_simulation_result(runtime, normalized)
    raise ValueError(
        f"不支持的结果选择器 `{selector}`；可使用 reference、candidate、latest 或已有结果文件。"
    )


def build_fair_comparison(
    runtime: ScenarioRuntime,
    reference_file: Path,
    candidate_file: Path,
    *,
    top_n: int = 5,
) -> dict:
    reference_payload = load_json(reference_file)
    candidate_payload = load_json(candidate_file)
    _require_successful_run(reference_payload, "基准")
    _require_successful_run(candidate_payload, "候选")

    reference_artifacts = _resolve_artifacts(runtime, reference_file, reference_payload)
    candidate_artifacts = _resolve_artifacts(runtime, candidate_file, candidate_payload)
    checks = _build_comparability_checks(
        reference_payload,
        candidate_payload,
        reference_artifacts,
        candidate_artifacts,
    )
    comparable = all(check["status"] == "pass" for check in checks if check["required"])

    metric_scope = {"lane_ids": [], "route_prefixes": [""]}
    reference_metrics = collect_metrics(reference_artifacts["outputs"], metric_scope)
    candidate_metrics = collect_metrics(candidate_artifacts["outputs"], metric_scope)
    metric_changes = _compare_global_metrics(reference_metrics, candidate_metrics)
    reference_edges = collect_edge_metrics(reference_artifacts["edge_metrics"])
    candidate_edges = collect_edge_metrics(candidate_artifacts["edge_metrics"])
    edge_changes = _compare_edges(reference_edges, candidate_edges, _edge_names(runtime.net_file))
    improved_edges = sorted(edge_changes, key=lambda row: row["improvement_score"], reverse=True)
    worsened_edges = sorted(edge_changes, key=lambda row: row["worsening_score"], reverse=True)
    improved_edges = [row for row in improved_edges if row["improvement_score"] > 0][:top_n]
    worsened_edges = [row for row in worsened_edges if row["worsening_score"] > 0][:top_n]
    signal_changes = _compare_signal_durations(reference_artifacts["net"], candidate_artifacts["net"])
    conclusion = _build_conclusion(comparable, metric_changes)
    focus_edge = (worsened_edges or improved_edges or [{}])[0].get("edge_id", "")

    return {
        "status": "success",
        "scenario_id": runtime.scenario_id,
        "scenario_name": runtime.name,
        "reference": _source_summary(reference_file, reference_payload),
        "candidate": _source_summary(candidate_file, candidate_payload),
        "comparability": {
            "strictly_comparable": comparable,
            "checks": checks,
            "passed_count": sum(check["status"] == "pass" for check in checks),
            "failed_count": sum(check["status"] == "fail" for check in checks),
        },
        "reference_metrics": reference_metrics,
        "candidate_metrics": candidate_metrics,
        "metric_changes": metric_changes,
        "signal_changes": signal_changes,
        "edge_changes": edge_changes,
        "top_improved_edges": improved_edges,
        "top_worsened_edges": worsened_edges,
        "conclusion": conclusion,
        "spatial_selection": _spatial_selection(runtime, focus_edge),
        "limitations": [
            "结论仅适用于当前场景、交通需求、仿真时长和随机种子。",
            "单一随机种子不能代表统计显著性；正式研究应采用多随机种子重复实验。",
        ],
    }


def _build_comparability_checks(
    reference_payload: dict,
    candidate_payload: dict,
    reference_artifacts: dict,
    candidate_artifacts: dict,
) -> list[dict]:
    reference_scenario = (reference_payload.get("scenario_runtime") or {}).get("scenario_id")
    candidate_scenario = (candidate_payload.get("scenario_runtime") or {}).get("scenario_id")
    reference_seed = reference_payload.get("random_seed")
    candidate_seed = candidate_payload.get("random_seed")
    checks = [
        _check("场景", reference_scenario, candidate_scenario, required=True),
        _check(
            "仿真时长",
            int(reference_payload.get("duration_seconds", 0) or 0),
            int(candidate_payload.get("duration_seconds", 0) or 0),
            required=True,
            unit="秒",
        ),
        _check("随机种子", reference_seed, candidate_seed, required=True, missing_is_failure=True),
        _check(
            "路网拓扑与相位放行关系",
            _network_control_signature(reference_artifacts["net"]),
            _network_control_signature(candidate_artifacts["net"]),
            required=True,
            hide_values=True,
        ),
        _check(
            "交通需求与车辆路线",
            _route_signature(reference_artifacts["route_files"]),
            _route_signature(candidate_artifacts["route_files"]),
            required=True,
            hide_values=True,
        ),
    ]
    return checks


def _check(
    name: str,
    reference: Any,
    candidate: Any,
    *,
    required: bool,
    unit: str = "",
    missing_is_failure: bool = False,
    hide_values: bool = False,
) -> dict:
    missing = reference in (None, "") or candidate in (None, "")
    matches = reference == candidate and not (missing and missing_is_failure)
    status = "pass" if matches else "fail"
    if hide_values:
        reference_label = "一致签名" if matches else "基准签名"
        candidate_label = "一致签名" if matches else "候选签名"
    else:
        reference_label = "未记录" if reference in (None, "") else f"{reference}{unit}"
        candidate_label = "未记录" if candidate in (None, "") else f"{candidate}{unit}"
    return {
        "name": name,
        "status": status,
        "required": required,
        "reference": reference_label,
        "candidate": candidate_label,
        "message": "一致" if matches else "不一致，不能作为严格公平对比",
    }


def _compare_global_metrics(reference: dict, candidate: dict) -> dict:
    keys = {
        "overall_avg_wait_s": "全网平均等待时间",
        "overall_time_loss_s": "全网平均时间损失",
        "arrived_vehicle_count": "仿真期完成车辆数",
        "max_halting_vehicles": "最大同时停车车辆数",
        "running_vehicle_count": "结束时仍在运行车辆数",
        "inserted_vehicle_count": "成功插入车辆数",
    }
    result = {}
    for key, label in keys.items():
        before = float(reference.get(key, 0.0))
        after = float(candidate.get(key, 0.0))
        result[key] = {
            "label": label,
            "reference": round(before, 3),
            "candidate": round(after, 3),
            "delta": round(after - before, 3),
        }
    return result


def _compare_edges(reference: dict[str, dict], candidate: dict[str, dict], names: dict[str, str]) -> list[dict]:
    rows = []
    for edge_id in sorted(set(reference) | set(candidate)):
        before = reference.get(edge_id, {})
        after = candidate.get(edge_id, {})
        before_sampled = max(float(before.get("sampled_seconds", 0.0)), 1.0)
        after_sampled = max(float(after.get("sampled_seconds", 0.0)), 1.0)
        before_wait_ratio = float(before.get("waiting_time_s", 0.0)) / before_sampled
        after_wait_ratio = float(after.get("waiting_time_s", 0.0)) / after_sampled
        before_loss_ratio = float(before.get("time_loss_s", 0.0)) / before_sampled
        after_loss_ratio = float(after.get("time_loss_s", 0.0)) / after_sampled
        speed_delta = float(after.get("mean_speed_mps", 0.0)) - float(before.get("mean_speed_mps", 0.0))
        wait_delta = after_wait_ratio - before_wait_ratio
        loss_delta = after_loss_ratio - before_loss_ratio
        worsening = min(100 * (0.4 * max(wait_delta, 0) + 0.35 * max(loss_delta, 0) + 0.25 * max(-speed_delta / 13.9, 0)), 100)
        improvement = min(100 * (0.4 * max(-wait_delta, 0) + 0.35 * max(-loss_delta, 0) + 0.25 * max(speed_delta / 13.9, 0)), 100)
        rows.append(
            {
                "edge_id": edge_id,
                "display_name": names.get(edge_id, f"道路 {edge_id}"),
                "reference_mean_speed_mps": round(float(before.get("mean_speed_mps", 0.0)), 3),
                "candidate_mean_speed_mps": round(float(after.get("mean_speed_mps", 0.0)), 3),
                "mean_speed_delta_mps": round(speed_delta, 3),
                "reference_waiting_ratio": round(before_wait_ratio, 4),
                "candidate_waiting_ratio": round(after_wait_ratio, 4),
                "waiting_ratio_delta": round(wait_delta, 4),
                "reference_time_loss_ratio": round(before_loss_ratio, 4),
                "candidate_time_loss_ratio": round(after_loss_ratio, 4),
                "time_loss_ratio_delta": round(loss_delta, 4),
                "improvement_score": round(improvement, 1),
                "worsening_score": round(worsening, 1),
            }
        )
    return rows


def _build_conclusion(comparable: bool, changes: dict) -> dict:
    if not comparable:
        return {
            "verdict": "不可严格比较",
            "evidence_level": "描述性观察",
            "message": "关键实验条件不一致，因此不能把指标差异归因于信号配时变化。",
        }
    wait_delta = changes["overall_avg_wait_s"]["delta"]
    loss_delta = changes["overall_time_loss_s"]["delta"]
    arrived_delta = changes["arrived_vehicle_count"]["delta"]
    halting_delta = changes["max_halting_vehicles"]["delta"]
    improvements = sum((wait_delta < -0.5, loss_delta < -0.5, arrived_delta > 0, halting_delta < 0))
    worsenings = sum((wait_delta > 0.5, loss_delta > 0.5, arrived_delta < 0, halting_delta > 0))
    if improvements >= 2 and worsenings == 0:
        verdict = "候选方案在本次实验中表现更好"
    elif worsenings >= 2 and improvements == 0:
        verdict = "候选方案在本次实验中表现更差"
    else:
        verdict = "候选方案存在权衡或无明显改善"
    return {
        "verdict": verdict,
        "evidence_level": "单随机种子仿真证据",
        "message": (
            f"在相同实验条件下，平均等待变化 {wait_delta:+.2f} 秒，"
            f"平均时间损失变化 {loss_delta:+.2f} 秒，完成车辆变化 {arrived_delta:+.0f} 辆，"
            f"最大同时停车车辆变化 {halting_delta:+.0f} 辆。"
        ),
    }


def _resolve_artifacts(runtime: ScenarioRuntime, result_file: Path, payload: dict) -> dict:
    run_dir = result_file.parent.parent / RUN_DIRS.get(result_file.name, "simulation")
    outputs = {}
    for key in ("statistics", "summary", "tripinfo", "queue"):
        outputs[key] = str(_existing_path((payload.get("outputs") or {}).get(key), run_dir / f"{key}.xml", key))
    edge_metrics = _existing_path(payload.get("edge_metrics_file"), run_dir / "edge_metrics.xml", "edge_metrics")
    net = _existing_path(payload.get("net_file"), run_dir / "parameterized_intersection.net.xml", "net", optional=True)
    if net is None:
        net = runtime.net_file
    route_files = []
    for configured in payload.get("route_files") or []:
        path = Path(str(configured))
        if path.exists():
            route_files.append(path)
        else:
            fallback = run_dir / path.name
            if fallback.exists():
                route_files.append(fallback)
    if not route_files:
        runtime_route = run_dir / "runtime_routes.rou.xml"
        route_files = [runtime_route if runtime_route.exists() else runtime.route_file]
    return {"outputs": outputs, "edge_metrics": edge_metrics, "net": net, "route_files": route_files}


def _existing_path(configured: Any, fallback: Path, label: str, optional: bool = False) -> Path | None:
    if configured:
        configured_path = Path(str(configured))
        if configured_path.exists():
            return configured_path
    if fallback.exists():
        return fallback
    if optional:
        return None
    raise FileNotFoundError(f"结果缺少 `{label}` 输出文件。")


def _network_control_signature(path: Path) -> str:
    root = ET.parse(path).getroot()
    payload = {
        "edges": sorted(
            (
                edge.get("id", ""),
                edge.get("function", ""),
                tuple((lane.get("id", ""), lane.get("index", "")) for lane in edge.findall("lane")),
            )
            for edge in root.findall("edge")
        ),
        "connections": sorted(
            (
                item.get("from", ""), item.get("to", ""), item.get("fromLane", ""),
                item.get("toLane", ""), item.get("tl", ""), item.get("linkIndex", ""),
            )
            for item in root.findall("connection")
        ),
        "signal_states": sorted(
            (
                item.get("id", ""), item.get("programID", ""), item.get("type", ""),
                tuple(phase.get("state", "") for phase in item.findall("phase")),
            )
            for item in root.findall("tlLogic")
        ),
    }
    return _hash_payload(payload)


def _route_signature(paths: list[Path]) -> str:
    roots = [ET.tostring(ET.parse(path).getroot(), encoding="unicode") for path in paths]
    return _hash_payload(sorted(roots))


def _compare_signal_durations(reference_net: Path, candidate_net: Path) -> list[dict]:
    before = _signal_duration_map(reference_net)
    after = _signal_duration_map(candidate_net)
    changes = []
    for key in sorted(set(before) | set(after)):
        before_values = before.get(key, [])
        after_values = after.get(key, [])
        if before_values != after_values:
            changes.append(
                {
                    "controller_id": key[0],
                    "program_id": key[1],
                    "reference_phase_durations_s": before_values,
                    "candidate_phase_durations_s": after_values,
                    "reference_cycle_seconds": round(sum(before_values), 3),
                    "candidate_cycle_seconds": round(sum(after_values), 3),
                }
            )
    return changes


def _signal_duration_map(path: Path) -> dict[tuple[str, str], list[float]]:
    root = ET.parse(path).getroot()
    return {
        (item.get("id", ""), item.get("programID", "0")): [
            float(phase.get("duration", 0) or 0) for phase in item.findall("phase")
        ]
        for item in root.findall("tlLogic")
    }


def _edge_names(net_file: Path) -> dict[str, str]:
    root = ET.parse(net_file).getroot()
    return {
        edge.get("id", ""): edge.get("name") or f"道路 {edge.get('id', '')}"
        for edge in root.findall("edge")
        if edge.get("id") and not edge.get("id", "").startswith(":")
    }


def _source_summary(result_file: Path, payload: dict) -> dict:
    return {
        "selector": payload.get("result_slot") or payload.get("variant") or result_file.stem,
        "duration_seconds": int(payload.get("duration_seconds", 0) or 0),
        "random_seed": payload.get("random_seed"),
        "signal_plan": payload.get("signal_plan", {}),
        "cfg_file": payload.get("cfg_file", ""),
        "animation": payload.get("animation", {}),
    }


def _spatial_selection(runtime: ScenarioRuntime, edge_id: str) -> dict:
    if not edge_id:
        return {}
    root = ET.parse(runtime.net_file).getroot()
    edge = root.find(f"edge[@id='{edge_id}']")
    lane_ids = [lane.get("id", "") for lane in edge.findall("lane")] if edge is not None else []
    return {
        "scenario_id": runtime.scenario_id,
        "selector_key": f"edge:{edge_id}",
        "object_type": "road",
        "display_name": edge.get("name") or f"道路 {edge_id}" if edge is not None else f"道路 {edge_id}",
        "edge_id": edge_id,
        "lane_id": lane_ids[0] if lane_ids else "",
        "lane_ids": lane_ids,
    }


def _require_successful_run(payload: dict, label: str) -> None:
    run = payload.get("run") or {}
    if run and not run.get("ok", False):
        raise ValueError(f"{label}仿真结果记录为失败，不能参与对比。")


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def format_fair_comparison_markdown(comparison: dict) -> str:
    comparability = comparison["comparability"]
    conclusion = comparison["conclusion"]
    lines = [
        "**任意两次仿真结果公平对比**",
        "",
        f"可比性结论：**{'通过' if comparability['strictly_comparable'] else '未通过'}**。",
        "",
        "| 检查项 | 基准 | 候选 | 状态 |",
        "|---|---|---|---|",
    ]
    for check in comparability["checks"]:
        status = "通过" if check["status"] == "pass" else "不通过"
        lines.append(f"| {check['name']} | {check['reference']} | {check['candidate']} | {status} |")
    lines.extend(
        [
            "",
            "**全局指标变化**",
            "",
            "| 指标 | 基准 | 候选 | 变化值 |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in comparison["metric_changes"].values():
        lines.append(f"| {row['label']} | {row['reference']:.2f} | {row['candidate']:.2f} | {row['delta']:+.2f} |")
    lines.extend(["", "**信号参数差异**", ""])
    if comparison["signal_changes"]:
        for change in comparison["signal_changes"]:
            lines.append(
                f"- 控制器 `{change['controller_id']}`："
                f"{change['reference_phase_durations_s']} → {change['candidate_phase_durations_s']} 秒；"
                f"周期 {change['reference_cycle_seconds']:g} → {change['candidate_cycle_seconds']:g} 秒。"
            )
    else:
        lines.append("- 两次仿真的信号相位时长没有变化。")

    lines.extend(["", "**道路影响**", ""])
    if comparison["top_improved_edges"]:
        names = "、".join(
            f"{row['display_name']} (`{row['edge_id']}`)" for row in comparison["top_improved_edges"][:3]
        )
        lines.append(f"- 改善较明显：{names}。")
    if comparison["top_worsened_edges"]:
        names = "、".join(
            f"{row['display_name']} (`{row['edge_id']}`)" for row in comparison["top_worsened_edges"][:3]
        )
        lines.append(f"- 恶化较明显：{names}。")
    lines.extend(
        [
            "",
            "**证据结论**",
            "",
            f"**{conclusion['verdict']}**。{conclusion['message']}",
            "",
            f"证据等级：{conclusion['evidence_level']}。{comparison['limitations'][1]}",
        ]
    )
    return "\n".join(lines)
