from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from simtrend_app.config import Settings
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.tools.base import ToolResult
from simtrend_app.tools.specs import SIGNAL_OPTIMIZATION_TOOL_SPECS, ToolSpec
from simtrend_app.tool_scripts.common import clip_text, format_runs, load_json


class AgentToolChain:
    def __init__(
        self,
        settings: Settings,
        incident_text: str,
        scenario: str | None = None,
        strategy: str = "signal_optimization",
        duration_seconds: int = 300,
        task_route: dict | None = None,
    ) -> None:
        self.settings = settings
        self.repo_root = Path(__file__).resolve().parents[2]
        self.runtime = ScenarioRuntime.from_project_dir(settings.sumo_project_path, scenario_id=scenario)
        self.runtime.validate_required_files()
        self.project_dir = self.runtime.project_dir

        self.incident_text = incident_text
        self.scenario = scenario or self.runtime.scenario_id
        self.strategy = strategy
        self.duration_seconds = duration_seconds
        self.task_route = dict(task_route or {})

        self.run_root = self.runtime.create_run_root(reuse_latest=self.settings.debug)
        run_dirs = self.runtime.run_subdirs(self.run_root)
        self.json_dir = run_dirs["json"]
        self.baseline_dir = run_dirs["baseline"]
        self.optimized_dir = run_dirs["optimized"]
        for run_dir in run_dirs.values():
            run_dir.mkdir(parents=True, exist_ok=True)

        self.paths = {
            "detection_json": self.json_dir / "detection.json",
            "signal_plan_json": self.json_dir / "signal_plan.json",
            "closure_analysis_json": self.json_dir / "closure_analysis.json",
            "baseline_json": self.json_dir / "baseline_result.json",
            "optimized_json": self.json_dir / "optimized_result.json",
            "comparison_json": self.json_dir / "comparison.json",
            "report_json": self.json_dir / "report.json",
        }
        self.runs: list[dict] = []

    def tool_functions(self) -> dict:
        return {
            "detect_incident": self.detect_incident,
            "build_signal_plan": self.build_signal_plan,
            "analyze_closure_impact": self.analyze_closure_impact,
            "run_baseline_simulation": self.run_baseline_simulation,
            "run_optimized_simulation": self.run_optimized_simulation,
            "compare_metrics": self.compare_metrics,
            "generate_report": self.generate_report,
        }

    def tool_specs(self) -> dict[str, ToolSpec]:
        return dict(SIGNAL_OPTIMIZATION_TOOL_SPECS)

    def available_next_tools(self) -> list[str]:
        available: list[str] = []
        if not self.paths["detection_json"].exists():
            available.append("detect_incident")
            return available
        if not self.paths["signal_plan_json"].exists():
            available.append("build_signal_plan")
            return available
        if not self.paths["closure_analysis_json"].exists():
            available.append("analyze_closure_impact")
            return available
        if not self.paths["baseline_json"].exists():
            available.append("run_baseline_simulation")
            return available
        if not self.paths["optimized_json"].exists():
            available.append("run_optimized_simulation")
            return available
        if not self.paths["comparison_json"].exists():
            available.append("compare_metrics")
            return available
        if not self.paths["report_json"].exists():
            available.append("generate_report")
            return available
        return available

    def state_snapshot(self) -> dict:
        available_next_tools = self.available_next_tools()
        snapshot = {
            "incident_text": self.incident_text,
            "scenario": self.scenario,
            "scenario_runtime": self.runtime.as_dict(),
            "strategy": self.strategy,
            "duration_seconds": self.duration_seconds,
            "task_route": self.task_route,
            "available_next_tools": available_next_tools,
            "completed_tools": [run["tool_name"] for run in self.runs if run.get("ok")],
            "failed_tools": [run["tool_name"] for run in self.runs if not run.get("ok")],
        }
        for key, path in self.paths.items():
            snapshot[key] = str(path) if path.exists() else None
        if self.paths["detection_json"].exists():
            snapshot["detection"] = load_json(self.paths["detection_json"])
        if self.paths["signal_plan_json"].exists():
            snapshot["signal_plan"] = load_json(self.paths["signal_plan_json"])
        if self.paths["closure_analysis_json"].exists():
            snapshot["closure_precheck"] = load_json(self.paths["closure_analysis_json"])["closure_precheck"]
        if self.paths["comparison_json"].exists():
            snapshot["comparison"] = load_json(self.paths["comparison_json"])
        snapshot["run_root"] = str(self.run_root)
        snapshot["available_tool_specs"] = [
            SIGNAL_OPTIMIZATION_TOOL_SPECS[name].as_dict(snapshot)
            for name in available_next_tools
        ]
        snapshot["tool_catalog"] = [
            spec.as_dict(snapshot)
            for spec in SIGNAL_OPTIMIZATION_TOOL_SPECS.values()
        ]
        return snapshot

    def detect_incident(self, incident_text: str | None = None, scenario: str | None = None) -> ToolResult:
        if incident_text:
            self.incident_text = incident_text
        if scenario is not None:
            self.scenario = scenario
        run = self._run_python_module(
            tool_name="detect_incident",
            label="事件识别脚本",
            module_name="simtrend_app.tool_scripts.detect_incident",
            module_args=[
                "--incident-text",
                self.incident_text,
                "--scenario",
                self.scenario,
                "--output",
                str(self.paths["detection_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)
        payload = load_json(self.paths["detection_json"])
        target = payload["target_plan"]["target_label"]
        return ToolResult(
            ok=True,
            message=f"已完成事件识别，当前重点对象为 {target}。",
            data={"target_label": target, "run_root": str(self.run_root), "runs": list(self.runs)},
        )

    def build_signal_plan(
        self,
        strategy: str | None = None,
        duration_seconds: int | None = None,
    ) -> ToolResult:
        if strategy:
            self.strategy = strategy
        if duration_seconds is not None:
            self.duration_seconds = duration_seconds
        run = self._run_python_module(
            tool_name="build_signal_plan",
            label="配时生成脚本",
            module_name="simtrend_app.tool_scripts.build_signal_plan",
            module_args=[
                "--detection-json",
                str(self.paths["detection_json"]),
                "--strategy",
                self.strategy,
                "--duration-seconds",
                str(self.duration_seconds),
                "--output",
                str(self.paths["signal_plan_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)
        payload = load_json(self.paths["signal_plan_json"])
        signal_plan = payload["signal_plan"]
        return ToolResult(
            ok=True,
            message=(
                "已生成基线与优化配时。"
                f"NS/EW 已从 {signal_plan['baseline']['north_south_green_s']}/{signal_plan['baseline']['east_west_green_s']}"
                f" 调整为 {signal_plan['optimized']['north_south_green_s']}/{signal_plan['optimized']['east_west_green_s']} 秒。"
            ),
            data={"signal_plan": signal_plan, "duration_seconds": payload["duration_seconds"], "runs": list(self.runs)},
        )

    def analyze_closure_impact(self) -> ToolResult:
        run = self._run_python_module(
            tool_name="analyze_closure_impact",
            label="封道影响预检脚本",
            module_name="simtrend_app.tool_scripts.analyze_closure_impact",
            module_args=[
                "--project-dir",
                str(self.project_dir),
                "--signal-plan-json",
                str(self.paths["signal_plan_json"]),
                "--output",
                str(self.paths["closure_analysis_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)
        precheck = load_json(self.paths["closure_analysis_json"])["closure_precheck"]
        if not precheck["enabled"]:
            message = "已完成封道影响预检，当前任务未启用车道封闭，无需额外处置。"
        elif precheck["requires_mitigation"]:
            message = (
                f"已完成封道影响预检：影响 {len(precheck['affected_route_ids'])} 条路线；"
                f"计划移除 {len(precheck['removed_flow_ids'])} 条车流、"
                f"延后 {len(precheck['delayed_flow_ids'])} 条车流。"
            )
        else:
            message = "已完成封道影响预检，当前交通需求不存在被完全阻断的路径。"
        return ToolResult(
            ok=True,
            message=message,
            data={"closure_precheck": precheck, "runs": list(self.runs)},
        )

    def run_baseline_simulation(self) -> ToolResult:
        run = self._run_python_module(
            tool_name="run_baseline_simulation",
            label="基线仿真脚本",
            module_name="simtrend_app.tool_scripts.run_baseline_simulation",
            module_args=[
                "--project-dir",
                str(self.project_dir),
                "--signal-plan-json",
                str(self.paths["signal_plan_json"]),
                "--output-dir",
                str(self.baseline_dir),
                "--output",
                str(self.paths["baseline_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)
        payload = load_json(self.paths["baseline_json"])
        sim_run = payload["run"]
        return ToolResult(
            ok=True,
            message=f"基线仿真已完成，返回码为 {sim_run['returncode']}。",
            data={"baseline_run": sim_run, "runs": list(self.runs)},
        )

    def run_optimized_simulation(self) -> ToolResult:
        run = self._run_python_module(
            tool_name="run_optimized_simulation",
            label="优化仿真脚本",
            module_name="simtrend_app.tool_scripts.run_optimized_simulation",
            module_args=[
                "--project-dir",
                str(self.project_dir),
                "--signal-plan-json",
                str(self.paths["signal_plan_json"]),
                "--output-dir",
                str(self.optimized_dir),
                "--output",
                str(self.paths["optimized_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)
        payload = load_json(self.paths["optimized_json"])
        sim_run = payload["run"]
        return ToolResult(
            ok=True,
            message=f"优化仿真已完成，返回码为 {sim_run['returncode']}。",
            data={"optimized_run": sim_run, "runs": list(self.runs)},
        )

    def compare_metrics(self) -> ToolResult:
        run = self._run_python_module(
            tool_name="compare_metrics",
            label="指标对比脚本",
            module_name="simtrend_app.tool_scripts.compare_metrics",
            module_args=[
                "--detection-json",
                str(self.paths["detection_json"]),
                "--signal-plan-json",
                str(self.paths["signal_plan_json"]),
                "--baseline-json",
                str(self.paths["baseline_json"]),
                "--optimized-json",
                str(self.paths["optimized_json"]),
                "--output",
                str(self.paths["comparison_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)
        payload = load_json(self.paths["comparison_json"])
        comparison = payload["comparison"]
        return ToolResult(
            ok=True,
            message=(
                "已完成指标对比。"
                f"重点方向平均排队变化 {comparison['target_avg_queue_delta_m']:+.2f} 米，"
                f"平均等待变化 {comparison['target_avg_wait_delta_s']:+.2f} 秒。"
            ),
            data={"comparison": comparison, "tradeoff_note": payload["tradeoff_note"], "runs": list(self.runs)},
        )

    def generate_report(self, strategy: str | None = None, scenario: str | None = None) -> ToolResult:
        if strategy:
            self.strategy = strategy
        if scenario is not None:
            self.scenario = scenario
        run = self._run_python_module(
            tool_name="generate_report",
            label="报告生成脚本",
            module_name="simtrend_app.tool_scripts.generate_report",
            module_args=[
                "--detection-json",
                str(self.paths["detection_json"]),
                "--signal-plan-json",
                str(self.paths["signal_plan_json"]),
                "--comparison-json",
                str(self.paths["comparison_json"]),
                "--closure-analysis-json",
                str(self.paths["closure_analysis_json"]),
                "--strategy",
                self.strategy,
                "--scenario",
                self.scenario,
                "--output",
                str(self.paths["report_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)

        detection_payload = load_json(self.paths["detection_json"])
        signal_plan_payload = load_json(self.paths["signal_plan_json"])
        closure_analysis_payload = load_json(self.paths["closure_analysis_json"])
        baseline_payload = load_json(self.paths["baseline_json"])
        optimized_payload = load_json(self.paths["optimized_json"])
        comparison_payload = load_json(self.paths["comparison_json"])
        report_payload = load_json(self.paths["report_json"])

        simulation_runs = [baseline_payload["run"], optimized_payload["run"]]
        message = (
            report_payload["human_message"]
            + "\n\n工具链日志：\n"
            + format_runs(self.runs)
            + "\n\nSimTrend Engine 命令日志：\n"
            + format_runs(simulation_runs)
        )
        return ToolResult(
            ok=True,
            message=message,
            data={
                "incident_text": self.incident_text,
                "strategy": self.strategy,
                "sumo_project_dir": str(self.project_dir),
                "cfg_file": baseline_payload["cfg_file"],
                "baseline_cfg_file": baseline_payload["cfg_file"],
                "optimized_cfg_file": optimized_payload["cfg_file"],
                "train_script": str(self.runtime.train_script),
                "gui_script": str(self.runtime.gui_script),
                "build_net_script": str(self.runtime.build_net_script),
                "sumo_binary": baseline_payload["sumo_binary"],
                "scenario": self.scenario or None,
                "scenario_runtime": self.runtime.as_dict(),
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
                "incident_context": report_payload.get("incident_context", signal_plan_payload.get("incident_context", {})),
                "closure_precheck": report_payload.get(
                    "closure_precheck",
                    closure_analysis_payload.get("closure_precheck", {}),
                ),
                "incident_impacts": report_payload.get("incident_impacts", comparison_payload.get("incident_impacts", {})),
                "pickup_waiting": report_payload.get("pickup_waiting", comparison_payload.get("pickup_waiting", {})),
                "demand_adjustments": report_payload.get(
                    "demand_adjustments",
                    comparison_payload.get("demand_adjustments", {}),
                ),
                "animations": {
                    "baseline": baseline_payload.get("animation", {}),
                    "optimized": optimized_payload.get("animation", {}),
                },
                "tool_chain_steps": report_payload["tool_chain_steps"],
                "run_root": str(self.run_root),
                "extra": {},
                "runs": list(self.runs),
                "simulation_runs": simulation_runs,
            },
        )

    def _run_python_module(self, tool_name: str, label: str, module_name: str, module_args: list[str]) -> dict:
        command = [sys.executable, "-m", module_name, *module_args]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            run = {
                "tool_name": tool_name,
                "label": label,
                "module": module_name,
                "ok": completed.returncode == 0,
                "command": command,
                "stdout": clip_text((completed.stdout or "").strip()),
                "stderr": clip_text((completed.stderr or "").strip()),
                "returncode": completed.returncode,
            }
        except subprocess.TimeoutExpired as exc:
            run = {
                "tool_name": tool_name,
                "label": label,
                "module": module_name,
                "ok": False,
                "command": command,
                "stdout": clip_text(((exc.stdout or "") if isinstance(exc.stdout, str) else "").strip()),
                "stderr": "命令执行超时：超过 180 秒。",
                "returncode": -1,
            }
        self.runs.append(run)
        return run

    def _failure(self, run: dict) -> ToolResult:
        return ToolResult(
            ok=False,
            message=f"{run['label']} 执行失败。\n\n工具链日志：\n{format_runs(self.runs)}",
            data={
                "run_root": str(self.run_root),
                "runs": list(self.runs),
                "tool_chain_steps": [item["tool_name"] for item in self.runs],
            },
        )
