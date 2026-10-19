from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from simtrend_app.config import Settings
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.tools.base import ToolResult
from simtrend_app.tool_scripts.common import clip_text, format_runs, load_json


def run_sumo_demo(
    settings: Settings,
    incident_text: str,
    strategy: str = "signal_optimization",
    scenario: str | None = None,
    duration_seconds: int | None = None,
    **extra: object,
) -> ToolResult:
    repo_root = Path(__file__).resolve().parents[2]
    runtime = ScenarioRuntime.from_project_dir(settings.sumo_project_path, scenario_id=scenario)
    project_dir = runtime.project_dir
    try:
        runtime.validate_required_files()
    except Exception as exc:
        return ToolResult(ok=False, message=str(exc))

    run_root = runtime.create_run_root(reuse_latest=settings.debug)
    run_dirs = runtime.run_subdirs(run_root)
    json_dir = run_dirs["json"]
    baseline_dir = run_dirs["baseline"]
    optimized_dir = run_dirs["optimized"]
    for run_dir in run_dirs.values():
        run_dir.mkdir(parents=True, exist_ok=True)

    detection_json = json_dir / "detection.json"
    signal_plan_json = json_dir / "signal_plan.json"
    baseline_json = json_dir / "baseline_result.json"
    optimized_json = json_dir / "optimized_result.json"
    comparison_json = json_dir / "comparison.json"
    report_json = json_dir / "report.json"

    tool_chain_runs: list[dict] = []
    steps = [
        (
            "事件识别脚本",
            "simtrend_app.tool_scripts.detect_incident",
            [
                "--incident-text",
                incident_text,
                "--scenario",
                scenario or "",
                "--output",
                str(detection_json),
            ],
        ),
        (
            "配时生成脚本",
            "simtrend_app.tool_scripts.build_signal_plan",
            [
                "--detection-json",
                str(detection_json),
                "--strategy",
                strategy,
                "--duration-seconds",
                str(duration_seconds or 300),
                "--output",
                str(signal_plan_json),
            ],
        ),
        (
            "基线仿真脚本",
            "simtrend_app.tool_scripts.run_baseline_simulation",
            [
                "--project-dir",
                str(project_dir),
                "--signal-plan-json",
                str(signal_plan_json),
                "--output-dir",
                str(baseline_dir),
                "--output",
                str(baseline_json),
            ],
        ),
        (
            "优化仿真脚本",
            "simtrend_app.tool_scripts.run_optimized_simulation",
            [
                "--project-dir",
                str(project_dir),
                "--signal-plan-json",
                str(signal_plan_json),
                "--output-dir",
                str(optimized_dir),
                "--output",
                str(optimized_json),
            ],
        ),
        (
            "指标对比脚本",
            "simtrend_app.tool_scripts.compare_metrics",
            [
                "--detection-json",
                str(detection_json),
                "--signal-plan-json",
                str(signal_plan_json),
                "--baseline-json",
                str(baseline_json),
                "--optimized-json",
                str(optimized_json),
                "--output",
                str(comparison_json),
            ],
        ),
        (
            "报告生成脚本",
            "simtrend_app.tool_scripts.generate_report",
            [
                "--detection-json",
                str(detection_json),
                "--signal-plan-json",
                str(signal_plan_json),
                "--comparison-json",
                str(comparison_json),
                "--strategy",
                strategy,
                "--scenario",
                scenario or "",
                "--output",
                str(report_json),
            ],
        ),
    ]

    for label, module_name, module_args in steps:
        run = _run_python_module(label, module_name, module_args, repo_root)
        tool_chain_runs.append(run)
        if not run["ok"]:
            return ToolResult(
                ok=False,
                message=f"{label} 执行失败。\n\n工具链日志：\n{format_runs(tool_chain_runs)}",
                data={
                    "run_root": str(run_root),
                    "extra": extra,
                    "runs": tool_chain_runs,
                    "tool_chain_steps": [step_label for step_label, _, _ in steps],
                },
            )

    detection_payload = load_json(detection_json)
    signal_plan_payload = load_json(signal_plan_json)
    baseline_payload = load_json(baseline_json)
    optimized_payload = load_json(optimized_json)
    comparison_payload = load_json(comparison_json)
    report_payload = load_json(report_json)

    simulation_runs = [baseline_payload["run"], optimized_payload["run"]]
    message = (
        report_payload["human_message"]
        + "\n\n工具链日志：\n"
        + format_runs(tool_chain_runs)
        + "\n\nSimTrend Engine 命令日志：\n"
        + format_runs(simulation_runs)
    )

    return ToolResult(
        ok=True,
        message=message,
        data={
            "incident_text": incident_text,
            "strategy": strategy,
            "sumo_project_dir": str(project_dir),
            "cfg_file": baseline_payload["cfg_file"],
            "train_script": str(runtime.train_script),
            "gui_script": str(runtime.gui_script),
            "build_net_script": str(runtime.build_net_script),
            "sumo_binary": baseline_payload["sumo_binary"],
            "scenario": scenario or runtime.scenario_id,
            "scenario_runtime": runtime.as_dict(),
            "duration_seconds": signal_plan_payload["duration_seconds"],
            "target_key": detection_payload["target_plan"]["target_key"],
            "target_label": detection_payload["target_plan"]["target_label"],
            "axis_key": detection_payload["target_plan"]["axis_key"],
            "axis_label": detection_payload["target_plan"]["axis_label"],
            "signal_plan": signal_plan_payload["signal_plan"],
            "baseline": comparison_payload["baseline_metrics"],
            "optimized": comparison_payload["optimized_metrics"],
            "comparison": comparison_payload["comparison"],
            "tradeoff_note": comparison_payload["tradeoff_note"],
            "demand_adjustments": report_payload.get(
                "demand_adjustments",
                comparison_payload.get("demand_adjustments", {}),
            ),
            "tool_chain_steps": report_payload["tool_chain_steps"],
            "run_root": str(run_root),
            "extra": extra,
            "runs": tool_chain_runs,
            "simulation_runs": simulation_runs,
        },
    )


def _run_python_module(label: str, module_name: str, module_args: list[str], workdir: Path) -> dict:
    command = [sys.executable, "-m", module_name, *module_args]
    try:
        completed = subprocess.run(
            command,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        return {
            "label": label,
            "module": module_name,
            "ok": completed.returncode == 0,
            "command": command,
            "stdout": clip_text((completed.stdout or "").strip()),
            "stderr": clip_text((completed.stderr or "").strip()),
            "returncode": completed.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "label": label,
            "module": module_name,
            "ok": False,
            "command": command,
            "stdout": clip_text(((exc.stdout or "") if isinstance(exc.stdout, str) else "").strip()),
            "stderr": "命令执行超时：超过 180 秒。",
            "returncode": -1,
        }
