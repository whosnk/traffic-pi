from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from simtrend_app.config import Settings
from simtrend_app.edge_metrics import write_edge_data_additional
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.simulation_diagnostics import (
    build_simulation_diagnosis,
    format_diagnosis_markdown,
)
from simtrend_app.tool_scripts.common import (
    build_output_paths,
    build_runtime_additional_files,
    build_safe_runtime_route_plan,
    find_sumo_binary,
    load_pickup_zones,
    run_simulation,
    save_json,
    write_sumocfg,
)
from simtrend_app.tool_scripts.render_replay_gif import render_replay_gif
from simtrend_app.tools.base import ToolResult


def parse_parameterized_signal_request(text: str) -> tuple[dict, list[str]]:
    controller_match = re.search(
        r"(?:信号)?控制器(?:\s*ID)?\s*(?:为|是|设为|[:：])?\s*[`\"]?([A-Za-z0-9_#.-]+)",
        text,
        flags=re.I,
    )
    phase_match = re.search(
        r"相位(?:时长|配时)\s*(?:设置为|设为|为|是|[:：])?\s*[\[（(]?"
        r"((?:\d+(?:\.\d+)?\s*[,，、]\s*)+\d+(?:\.\d+)?)",
        text,
    )
    duration_match = re.search(r"(?:运行|仿真)(?:时长)?\s*(\d{2,4})\s*秒", text)
    seed_match = re.search(r"(?:随机)?种子\s*(?:为|是|设为|[:：])?\s*(\d+)", text)
    program_match = re.search(r"程序(?:\s*ID)?\s*(?:为|是|设为|[:：])?\s*([A-Za-z0-9_.-]+)", text)

    missing = []
    if not controller_match:
        missing.append("信号控制器 ID")
    if not phase_match:
        missing.append("完整相位时长数组")
    if missing:
        return {}, missing

    phase_durations = [
        float(value) if "." in value else int(value)
        for value in re.split(r"\s*[,，、]\s*", phase_match.group(1))
    ]
    return {
        "controller_id": controller_match.group(1),
        "program_id": program_match.group(1) if program_match else "0",
        "phase_durations": phase_durations,
        "duration_seconds": int(duration_match.group(1)) if duration_match else 600,
        "random_seed": int(seed_match.group(1)) if seed_match else 42,
        "render_animation": "动画" in text or "回放" in text,
        "result_slot": (
            "reference"
            if any(word in text for word in ("保存为基准", "作为基准", "基准方案"))
            else "candidate"
            if any(word in text for word in ("保存为候选", "作为候选", "候选方案"))
            else "latest"
        ),
    }, []


def evaluate_signal_plan(
    settings: Settings,
    controller_id: str,
    phase_durations: list,
    duration_seconds: int = 600,
    random_seed: int = 42,
    program_id: str = "0",
    render_animation: bool = False,
    result_slot: str = "latest",
) -> ToolResult:
    runtime = ScenarioRuntime.from_project_dir(settings.sumo_project_dir)
    try:
        runtime.validate_required_files()
        duration = max(60, min(int(duration_seconds), 3600))
        seed = max(0, min(int(random_seed), 2_147_483_647))
        network_tree, plan = _build_parameterized_signal_tree(
            runtime.net_file,
            controller_id=controller_id,
            program_id=program_id,
            phase_durations=phase_durations,
        )
        slot = str(result_slot or "latest").strip().lower()
        if slot not in {"latest", "reference", "candidate"}:
            raise SignalPlanValidationError(
                f"不支持的结果槽 `{result_slot}`。",
                details={"allowed_result_slots": ["latest", "reference", "candidate"]},
            )
        run_root = _prepare_run_root(runtime, slot)
        json_dir = run_root / "json"
        simulation_dir = run_root / "simulation"
        json_dir.mkdir(parents=True, exist_ok=True)
        simulation_dir.mkdir(parents=True, exist_ok=True)

        network_file = simulation_dir / "parameterized_intersection.net.xml"
        network_file.parent.mkdir(parents=True, exist_ok=True)
        network_tree.write(network_file, encoding="UTF-8", xml_declaration=True)
        plan.update(
            {
                "duration_seconds": duration,
                "random_seed": seed,
                "scenario_id": runtime.scenario_id,
                "result_slot": slot,
            }
        )
        plan_file = json_dir / "parameterized_signal_plan.json"
        save_json(plan_file, plan)

        pickup_zones = load_pickup_zones(runtime.project_dir)
        route_plan = build_safe_runtime_route_plan(
            runtime.route_file,
            network_file,
            simulation_dir,
            {},
            duration,
            pickup_zones=pickup_zones,
        )
        additional_files = build_runtime_additional_files(
            simulation_dir,
            {},
            duration,
            pickup_zones=pickup_zones,
        )
        edge_metrics_file = simulation_dir / "edge_metrics.xml"
        edge_metrics_additional = simulation_dir / "edge_metrics.add.xml"
        write_edge_data_additional(edge_metrics_additional, edge_metrics_file, duration)
        additional_files.append(edge_metrics_additional)

        cfg_file = simulation_dir / "parameterized_signal.sumocfg"
        write_sumocfg(
            cfg_file,
            network_file,
            route_plan["route_files"],
            duration,
            additional_files=additional_files,
        )
        outputs = build_output_paths(simulation_dir)
        run = run_simulation(
            label="参数化信号方案 SimTrend 仿真",
            sumo_binary=find_sumo_binary("sumo"),
            cfg_path=cfg_file,
            workdir=runtime.project_dir,
            duration=duration,
            outputs=outputs,
            random_seed=seed,
        )
        animation = {}
        if run["ok"] and render_animation:
            animation = render_replay_gif(
                net_file=network_file,
                fcd_file=outputs["fcd"],
                output_file=simulation_dir / "parameterized_replay.gif",
                duration_seconds=duration,
                title="Parameterized signal replay",
            )

        result_file = json_dir / "parameterized_result.json"
        result_payload = {
            "workflow_type": "parameterized_signal_simulation",
            "variant": "parameterized",
            "variant_label": "参数化信号方案",
            "scenario_runtime": runtime.as_dict(),
            "duration_seconds": duration,
            "random_seed": seed,
            "result_slot": slot,
            "signal_plan": plan,
            "cfg_file": str(cfg_file),
            "net_file": str(network_file),
            "route_files": [str(path) for path in route_plan["route_files"]],
            "additional_files": [str(path) for path in additional_files],
            "outputs": {key: str(value) for key, value in outputs.items()},
            "edge_metrics_file": str(edge_metrics_file),
            "demand_adjustment": route_plan["demand_adjustment"],
            "pickup_waiting": route_plan["pickup_waiting"],
            "animation": animation,
            "run": run,
        }
        save_json(result_file, result_payload)
        if not run["ok"]:
            return ToolResult(
                ok=False,
                message="参数化信号方案已通过校验，但真实仿真执行失败。",
                data={
                    "signal_plan": plan,
                    "run": run,
                    "error": {
                        "code": "SIMULATION_FAILED",
                        "message": run.get("stderr") or "仿真程序返回失败状态",
                        "recoverable": True,
                    },
                },
            )

        diagnosis = build_simulation_diagnosis(runtime, result_file, result_payload, top_n=5)
        diagnosis_file = json_dir / "simulation_diagnosis.json"
        save_json(diagnosis_file, diagnosis)
        result_payload["diagnosis_json"] = str(diagnosis_file)
        save_json(result_file, result_payload)
        message = _format_plan_summary(plan) + "\n\n" + format_diagnosis_markdown(diagnosis)
        return ToolResult(
            ok=True,
            message=message,
            data={
                "workflow_type": "parameterized_signal_simulation",
                "signal_plan": plan,
                "diagnosis": diagnosis,
                "result_json": str(result_file),
                "diagnosis_json": str(diagnosis_file),
                "cfg_file": str(cfg_file),
                "animation": animation,
                "run": run,
                "spatial_selection": diagnosis.get("spatial_selection", {}),
            },
        )
    except SignalPlanValidationError as exc:
        return ToolResult(
            ok=False,
            message=f"信号参数未通过校验：{exc}",
            data={
                "error": {
                    "code": "INVALID_SIGNAL_PARAMETERS",
                    "message": str(exc),
                    "details": exc.details,
                    "recoverable": True,
                }
            },
        )
    except (FileNotFoundError, ValueError, ET.ParseError, OSError) as exc:
        return ToolResult(
            ok=False,
            message=f"参数化信号仿真工具执行失败：{exc}",
            data={
                "error": {
                    "code": "TOOL_EXECUTION_FAILED",
                    "message": str(exc),
                    "recoverable": True,
                }
            },
        )


class SignalPlanValidationError(ValueError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def write_parameterized_signal_network(
    base_net_file: Path,
    output_net_file: Path,
    *,
    controller_id: str,
    phase_durations: list,
    program_id: str = "0",
) -> dict:
    tree, plan = _build_parameterized_signal_tree(
        base_net_file,
        controller_id=controller_id,
        phase_durations=phase_durations,
        program_id=program_id,
    )
    output_net_file.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_net_file, encoding="UTF-8", xml_declaration=True)
    return plan


def _build_parameterized_signal_tree(
    base_net_file: Path,
    *,
    controller_id: str,
    phase_durations: list,
    program_id: str = "0",
) -> tuple[ET.ElementTree, dict]:
    tree = ET.parse(base_net_file)
    root = tree.getroot()
    available = [
        {
            "controller_id": item.get("id", ""),
            "program_id": item.get("programID", ""),
            "phase_count": len(item.findall("phase")),
        }
        for item in root.findall("tlLogic")
    ]
    target = next(
        (
            item
            for item in root.findall("tlLogic")
            if item.get("id") == controller_id and item.get("programID", "0") == str(program_id)
        ),
        None,
    )
    if target is None:
        raise SignalPlanValidationError(
            f"未找到信号控制器 `{controller_id}` 的程序 `{program_id}`。",
            details={"available_controllers": available},
        )
    if target.get("type", "static") != "static":
        raise SignalPlanValidationError(
            "当前工具仅支持 static 定时信号控制器，不直接覆盖感应式控制程序。",
            details={"controller_type": target.get("type")},
        )

    phases = target.findall("phase")
    if len(phase_durations) != len(phases):
        raise SignalPlanValidationError(
            f"控制器共有 {len(phases)} 个相位，但收到 {len(phase_durations)} 个相位时长。",
            details={
                "required_phase_count": len(phases),
                "current_phase_durations": [_number(phase.get("duration")) for phase in phases],
                "phase_states": [phase.get("state", "") for phase in phases],
            },
        )

    durations = [_validated_duration(value, phase.get("state", ""), index) for index, (value, phase) in enumerate(zip(phase_durations, phases), start=1)]
    cycle = sum(durations)
    if not 20 <= cycle <= 240:
        raise SignalPlanValidationError(
            f"信号周期为 {cycle:g} 秒，应在 20-240 秒范围内。",
            details={"cycle_seconds": cycle},
        )

    original_durations = [_number(phase.get("duration")) for phase in phases]
    phase_rows = []
    for index, (phase, original, adjusted) in enumerate(zip(phases, original_durations, durations), start=1):
        phase.set("duration", _format_duration(adjusted))
        phase_rows.append(
            {
                "phase_index": index - 1,
                "state": phase.get("state", ""),
                "phase_type": _phase_type(phase.get("state", "")),
                "original_duration_s": original,
                "applied_duration_s": adjusted,
                "delta_s": round(adjusted - original, 3),
            }
        )

    plan = {
        "controller_id": controller_id,
        "program_id": str(program_id),
        "controller_type": target.get("type", "static"),
        "original_phase_durations_s": original_durations,
        "applied_phase_durations_s": durations,
        "original_cycle_seconds": round(sum(original_durations), 3),
        "applied_cycle_seconds": round(cycle, 3),
        "phases": phase_rows,
        "validation": {
            "ok": True,
            "rules": [
                "绿灯相位 5-120 秒",
                "黄灯相位 2-10 秒",
                "全红相位 1-10 秒",
                "完整周期 20-240 秒",
            ],
        },
    }
    return tree, plan


def _validated_duration(value: Any, state: str, phase_index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SignalPlanValidationError(f"第 {phase_index} 个相位时长必须是数字。")
    duration = float(value)
    phase_type = _phase_type(state)
    minimum, maximum = {
        "green": (5.0, 120.0),
        "yellow": (2.0, 10.0),
        "all_red": (1.0, 10.0),
    }[phase_type]
    if not minimum <= duration <= maximum:
        label = {"green": "绿灯", "yellow": "黄灯", "all_red": "全红"}[phase_type]
        raise SignalPlanValidationError(
            f"第 {phase_index} 个{label}相位为 {duration:g} 秒，应在 {minimum:g}-{maximum:g} 秒范围内。",
            details={"phase_index": phase_index - 1, "phase_type": phase_type, "state": state},
        )
    return round(duration, 3)


def _phase_type(state: str) -> str:
    if any(char in state for char in "Gg"):
        return "green"
    if any(char in state for char in "yY"):
        return "yellow"
    return "all_red"


def _number(value: Any) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return 0.0


def _format_duration(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.3f}".rstrip("0").rstrip(".")


def _prepare_run_root(runtime: ScenarioRuntime, result_slot: str = "latest") -> Path:
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:12]
    run_root = runtime.agent_runs_dir / f"parameterized_{result_slot}_{suffix}"
    run_root.mkdir(parents=True, exist_ok=False)
    return run_root


def _format_plan_summary(plan: dict) -> str:
    before = ", ".join(f"{value:g}" for value in plan["original_phase_durations_s"])
    after = ", ".join(f"{value:g}" for value in plan["applied_phase_durations_s"])
    return "\n".join(
        [
            "**参数化信号方案执行结果**",
            "",
            f"- 信号控制器：`{plan['controller_id']}`（程序 `{plan['program_id']}`）",
            f"- 相位时长：[{before}] → [{after}] 秒",
            f"- 信号周期：{plan['original_cycle_seconds']:g} → {plan['applied_cycle_seconds']:g} 秒",
            f"- 仿真时长：{plan['duration_seconds']} 秒；随机种子：{plan['random_seed']}",
            f"- 结果槽：`{plan['result_slot']}`",
            "- 参数校验与真实仿真均已成功。该结果只评价本次指定参数，不自动宣称其优于基线。",
        ]
    )
