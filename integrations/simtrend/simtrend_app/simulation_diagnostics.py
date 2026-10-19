from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from uuid import uuid4

from simtrend_app.config import Settings
from simtrend_app.edge_metrics import collect_edge_metrics
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.tool_scripts.common import collect_metrics, load_json, save_json
from simtrend_app.tools.base import ToolResult


RESULT_FILES = {
    "optimized": "optimized_result.json",
    "baseline": "baseline_result.json",
    "adjusted_demand": "adjusted_demand_result.json",
    "reference_demand": "reference_demand_result.json",
    "parameterized": "parameterized_result.json",
}

VARIANT_DIRS = {
    "optimized": "optimized",
    "baseline": "baseline",
    "adjusted_demand": "adjusted_demand",
    "reference_demand": "reference_demand",
    "parameterized": "simulation",
}


def diagnose_simulation_result(
    settings: Settings,
    variant: str = "latest",
    top_n: int = 5,
) -> ToolResult:
    runtime = ScenarioRuntime.from_project_dir(settings.sumo_project_dir)
    try:
        result_file = find_simulation_result(runtime, variant)
        result_payload = load_json(result_file)
        diagnosis = build_simulation_diagnosis(
            runtime,
            result_file,
            result_payload,
            top_n=max(1, min(int(top_n), 10)),
        )
    except (FileNotFoundError, ValueError, ET.ParseError, OSError) as exc:
        return ToolResult(
            ok=False,
            message=f"无法诊断最近一次仿真：{exc}",
            data={
                "error": {
                    "code": "DIAGNOSIS_INPUT_NOT_FOUND",
                    "message": str(exc),
                    "recoverable": True,
                }
            },
        )

    diagnosis_file = result_file.parent / f"simulation_diagnosis_{uuid4().hex}.json"
    save_json(diagnosis_file, diagnosis)
    return ToolResult(
        ok=True,
        message=format_diagnosis_markdown(diagnosis),
        data={
            "workflow_type": "simulation_diagnosis",
            "diagnosis": diagnosis,
            "diagnosis_json": str(diagnosis_file),
            "spatial_selection": diagnosis.get("spatial_selection", {}),
        },
    )


def find_simulation_result(runtime: ScenarioRuntime, variant: str = "latest") -> Path:
    normalized = str(variant or "latest").strip().lower()
    if normalized != "latest" and normalized not in RESULT_FILES:
        raise ValueError(f"不支持的仿真方案 `{variant}`。")
    names = list(RESULT_FILES.values()) if normalized == "latest" else [RESULT_FILES[normalized]]
    candidates = [
        path
        for name in names
        for path in runtime.agent_runs_dir.glob(f"*/json/{name}")
        if path.is_file()
    ]
    if not candidates:
        variant_label = "最近一次" if normalized == "latest" else normalized
        raise FileNotFoundError(f"未找到{variant_label}成功仿真的结果文件，请先运行一次仿真。")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def build_simulation_diagnosis(
    runtime: ScenarioRuntime,
    result_file: Path,
    result_payload: dict,
    *,
    top_n: int = 5,
) -> dict:
    variant = _variant_from_result_file(result_file)
    run_dir = result_file.parent.parent / VARIANT_DIRS[variant]
    edge_metrics_file = _resolve_output_file(
        result_payload.get("edge_metrics_file"),
        run_dir / "edge_metrics.xml",
    )
    if edge_metrics_file is None:
        raise FileNotFoundError(
            "该仿真没有道路级指标文件。请重新运行一次仿真，新结果会自动记录诊断数据。"
        )

    edge_metrics = collect_edge_metrics(edge_metrics_file)
    if not edge_metrics:
        raise ValueError("道路级指标文件为空，无法识别交通瓶颈。")

    edge_context, successors = _load_edge_context(runtime)
    ranked = _rank_bottlenecks(edge_metrics, edge_context)
    bottlenecks = ranked[:top_n]
    bottleneck_ids = {row["edge_id"] for row in bottlenecks}
    for row in bottlenecks:
        row["possible_downstream_spread"] = [
            edge_context.get(edge_id, {}).get("display_name", f"道路 {edge_id}")
            for edge_id in successors.get(row["edge_id"], [])
            if edge_id in bottleneck_ids
        ][:3]

    overall_metrics = _collect_overall_metrics(result_payload, run_dir)
    top = bottlenecks[0] if bottlenecks else None
    high_count = sum(1 for row in ranked if row["severity"] == "高")
    medium_count = sum(1 for row in ranked if row["severity"] == "中")
    diagnosis = {
        "status": "success",
        "scenario_id": runtime.scenario_id,
        "scenario_name": runtime.name,
        "source": {
            "variant": variant,
            "variant_label": _variant_label(variant),
            "duration_seconds": int(result_payload.get("duration_seconds", 0) or 0),
            "result_file": str(result_file),
            "edge_metrics_file": str(edge_metrics_file),
        },
        "overall_metrics": overall_metrics,
        "summary": {
            "analyzed_edge_count": len(edge_metrics),
            "high_pressure_edge_count": high_count,
            "medium_pressure_edge_count": medium_count,
            "overall_severity": top["severity"] if top else "低",
            "primary_bottleneck": top["display_name"] if top else "未识别到明显瓶颈",
            "primary_bottleneck_edge_id": top["edge_id"] if top else "",
        },
        "bottlenecks": bottlenecks,
        "limitations": [
            "诊断基于当前仿真周期内的道路聚合指标，用于筛查异常位置，不等同于现场交通调查结论。",
            "瓶颈评分用于相对排序；道路功能、限速和交通组织差异仍需结合场景解释。",
        ],
        "spatial_selection": _build_spatial_selection(runtime, top, edge_context),
    }
    return diagnosis


def _rank_bottlenecks(edge_metrics: dict[str, dict], edge_context: dict[str, dict]) -> list[dict]:
    rows = []
    for edge_id, metrics in edge_metrics.items():
        sampled = float(metrics.get("sampled_seconds", 0.0))
        if sampled <= 0:
            continue
        entered = float(metrics.get("vehicle_entered", 0.0))
        left = float(metrics.get("vehicle_left", 0.0))
        speed = float(metrics.get("mean_speed_mps", 0.0))
        density = float(metrics.get("density_veh_per_km", 0.0))
        waiting = float(metrics.get("waiting_time_s", 0.0))
        time_loss = float(metrics.get("time_loss_s", 0.0))
        waiting_ratio = min(waiting / sampled, 1.0)
        time_loss_ratio = min(time_loss / sampled, 1.0)
        speed_stress = min(max((13.9 - speed) / 13.9, 0.0), 1.0)
        density_stress = min(density / 20.0, 1.0)
        accumulation = max(entered - left, 0.0)
        accumulation_ratio = min(accumulation / max(entered, 1.0), 1.0)
        reliability = min(sampled / 60.0, 1.0)
        score = 100 * reliability * (
            0.35 * waiting_ratio
            + 0.30 * time_loss_ratio
            + 0.20 * speed_stress
            + 0.10 * density_stress
            + 0.05 * accumulation_ratio
        )
        anomalies = _classify_anomalies(
            waiting_ratio,
            time_loss_ratio,
            speed,
            density,
            accumulation,
            entered,
        )
        context = edge_context.get(edge_id, {})
        rows.append(
            {
                "edge_id": edge_id,
                "display_name": context.get("display_name", f"道路 {edge_id}"),
                "lane_ids": context.get("lane_ids", []),
                "score": round(score, 1),
                "severity": "高" if score >= 55 else "中" if score >= 30 else "低",
                "anomaly_types": anomalies or ["综合运行压力"],
                "evidence": {
                    "mean_speed_mps": round(speed, 2),
                    "mean_speed_kmh": round(speed * 3.6, 1),
                    "density_veh_per_km": round(density, 2),
                    "waiting_time_s": round(waiting, 2),
                    "waiting_ratio": round(waiting_ratio, 3),
                    "time_loss_s": round(time_loss, 2),
                    "time_loss_ratio": round(time_loss_ratio, 3),
                    "vehicle_entered": round(entered, 1),
                    "vehicle_left": round(left, 1),
                    "vehicle_accumulation": round(accumulation, 1),
                    "sampled_seconds": round(sampled, 1),
                },
                "recommendation": _diagnostic_recommendation(anomalies),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            float(row["score"]),
            float(row["evidence"]["waiting_time_s"]),
            float(row["evidence"]["time_loss_s"]),
        ),
        reverse=True,
    )


def _classify_anomalies(
    waiting_ratio: float,
    time_loss_ratio: float,
    speed: float,
    density: float,
    accumulation: float,
    entered: float,
) -> list[str]:
    anomalies = []
    if waiting_ratio >= 0.15:
        anomalies.append("停车等待偏高")
    if time_loss_ratio >= 0.25:
        anomalies.append("时间损失偏高")
    if speed < 5.0:
        anomalies.append("运行速度偏低")
    if density >= 10.0:
        anomalies.append("交通密度偏高")
    if accumulation >= 2 and accumulation / max(entered, 1.0) >= 0.25:
        anomalies.append("车辆积压")
    return anomalies


def _diagnostic_recommendation(anomalies: list[str]) -> str:
    if "车辆积压" in anomalies or "停车等待偏高" in anomalies:
        return "优先核查下游放行能力、车道占用和交叉口控制，必要时开展针对性疏导。"
    if "运行速度偏低" in anomalies or "时间损失偏高" in anomalies:
        return "建议检查道路连接、转向冲突及相邻节点协调，并与上下游指标联合判断。"
    if "交通密度偏高" in anomalies:
        return "建议持续观察流量增长与排队形成过程，评估是否需要需求分流。"
    return "建议结合道路功能和相邻道路指标复核，暂不直接判定控制措施。"


def _load_edge_context(runtime: ScenarioRuntime) -> tuple[dict[str, dict], dict[str, list[str]]]:
    root = ET.parse(runtime.net_file).getroot()
    pickup_names = {
        str(zone.get("edge_id")): str(zone.get("name"))
        for zone in runtime.map_config.get("pickup_zones", [])
        if zone.get("edge_id")
    }
    context = {}
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if not edge_id or edge_id.startswith(":") or edge.get("function") == "internal":
            continue
        name = pickup_names.get(edge_id) or edge.get("name") or f"道路 {edge_id}"
        context[edge_id] = {
            "display_name": name,
            "lane_ids": [lane.get("id", "") for lane in edge.findall("lane") if lane.get("id")],
        }
    successors: dict[str, list[str]] = {}
    for connection in root.findall("connection"):
        from_edge = connection.get("from", "")
        to_edge = connection.get("to", "")
        if from_edge in context and to_edge in context:
            successors.setdefault(from_edge, [])
            if to_edge not in successors[from_edge]:
                successors[from_edge].append(to_edge)
    return context, successors


def _collect_overall_metrics(result_payload: dict, run_dir: Path) -> dict:
    outputs = {}
    for key in ("statistics", "summary", "tripinfo", "queue"):
        fallback = run_dir / f"{key}.xml"
        resolved = _resolve_output_file((result_payload.get("outputs") or {}).get(key), fallback)
        if resolved is None:
            return {}
        outputs[key] = str(resolved)
    return collect_metrics(outputs, {"lane_ids": [], "route_prefixes": [""]})


def _resolve_output_file(configured_path: Any, fallback: Path) -> Path | None:
    if configured_path:
        configured = Path(str(configured_path))
        if configured.exists():
            return configured
    return fallback if fallback.exists() else None


def _variant_from_result_file(result_file: Path) -> str:
    for variant, filename in RESULT_FILES.items():
        if result_file.name == filename:
            return variant
    raise ValueError(f"无法识别仿真结果类型：{result_file.name}")


def _variant_label(variant: str) -> str:
    return {
        "optimized": "优化方案",
        "baseline": "基线方案",
        "adjusted_demand": "调整后需求方案",
        "reference_demand": "原始需求方案",
        "parameterized": "参数化信号方案",
    }[variant]


def _build_spatial_selection(
    runtime: ScenarioRuntime,
    top: dict | None,
    edge_context: dict[str, dict],
) -> dict:
    if not top:
        return {}
    edge_id = str(top["edge_id"])
    lane_ids = edge_context.get(edge_id, {}).get("lane_ids", [])
    return {
        "scenario_id": runtime.scenario_id,
        "selector_key": f"edge:{edge_id}",
        "object_type": "road",
        "display_name": top["display_name"],
        "edge_id": edge_id,
        "lane_id": lane_ids[0] if lane_ids else "",
        "lane_ids": lane_ids,
    }


def format_diagnosis_markdown(diagnosis: dict) -> str:
    source = diagnosis["source"]
    summary = diagnosis["summary"]
    overall = diagnosis.get("overall_metrics") or {}
    lines = [
        "**仿真结果诊断**",
        "",
        f"诊断对象：{diagnosis['scenario_name']} · {source['variant_label']} · {source['duration_seconds']} 秒",
        f"综合判断：**{summary['overall_severity']}压力**；首要瓶颈为 **{summary['primary_bottleneck']}**。",
        "",
        "**全局运行概况**",
        "",
    ]
    if overall:
        lines.extend(
            [
                f"- 平均等待时间：{overall['overall_avg_wait_s']:.2f} 秒",
                f"- 仿真期完成车辆：{overall['arrived_vehicle_count']:.0f} 辆",
                f"- 最大同时停车车辆：{overall['max_halting_vehicles']:.0f} 辆",
                f"- 仿真结束时仍在运行：{overall['running_vehicle_count']:.0f} 辆",
            ]
        )
    else:
        lines.append("- 全局输出不完整，本次仅使用道路级指标诊断。")

    lines.extend(
        [
            "",
            "**重点瓶颈道路**",
            "",
            "| 排名 | 道路 | 压力 | 速度 | 等待占比 | 时间损失占比 | 异常证据 |",
            "|---:|---|---:|---:|---:|---:|---|",
        ]
    )
    for index, row in enumerate(diagnosis["bottlenecks"], start=1):
        evidence = row["evidence"]
        lines.append(
            f"| {index} | {row['display_name']} (`{row['edge_id']}`) | "
            f"{row['severity']} {row['score']:.1f} | {evidence['mean_speed_kmh']:.1f} km/h | "
            f"{evidence['waiting_ratio'] * 100:.1f}% | {evidence['time_loss_ratio'] * 100:.1f}% | "
            f"{'、'.join(row['anomaly_types'])} |"
        )
    if diagnosis["bottlenecks"]:
        top = diagnosis["bottlenecks"][0]
        lines.extend(["", "**诊断建议**", "", f"- {top['recommendation']}"])
        if top.get("possible_downstream_spread"):
            lines.append(f"- 可能向下游关联道路传播：{'、'.join(top['possible_downstream_spread'])}。")
        lines.append("- 首要瓶颈已同步到空间对象选择器，可继续针对该道路发起查询或仿真任务。")
    lines.extend(["", f"数据说明：{diagnosis['limitations'][0]}"])
    return "\n".join(lines)
