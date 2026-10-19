from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from simtrend_app.config import Settings
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.tool_scripts.common import clip_text, format_runs, load_json
from simtrend_app.tools.base import ToolResult
from simtrend_app.tools.specs import DEMAND_IMPACT_TOOL_SPECS, ToolSpec


class DemandImpactToolChain:
    def __init__(
        self,
        settings: Settings,
        request_text: str,
        scenario: str | None = None,
        duration_seconds: int = 300,
        task_route: dict | None = None,
    ) -> None:
        self.settings = settings
        self.repo_root = Path(__file__).resolve().parents[2]
        self.runtime = ScenarioRuntime.from_project_dir(settings.sumo_project_path, scenario_id=scenario)
        self.runtime.validate_required_files()
        self.project_dir = self.runtime.project_dir
        self.request_text = request_text
        self.scenario = scenario or self.runtime.scenario_id
        self.duration_seconds = duration_seconds
        self.task_route = dict(task_route or {})

        self.run_root = self.runtime.create_run_root(reuse_latest=self.settings.debug)
        self.json_dir = self.run_root / "json"
        self.reference_dir = self.run_root / "reference_demand"
        self.adjusted_dir = self.run_root / "adjusted_demand"
        for run_dir in (self.json_dir, self.reference_dir, self.adjusted_dir):
            run_dir.mkdir(parents=True, exist_ok=True)

        self.paths = {
            "demand_plan_json": self.json_dir / "demand_plan.json",
            "reference_json": self.json_dir / "reference_demand_result.json",
            "adjusted_json": self.json_dir / "adjusted_demand_result.json",
            "demand_comparison_json": self.json_dir / "demand_comparison.json",
            "demand_report_json": self.json_dir / "demand_report.json",
        }
        self.runs: list[dict] = []

    def tool_functions(self) -> dict:
        return {
            "prepare_demand_plan": self.prepare_demand_plan,
            "run_reference_demand_simulation": self.run_reference_demand_simulation,
            "run_adjusted_demand_simulation": self.run_adjusted_demand_simulation,
            "compare_demand_impact": self.compare_demand_impact,
            "generate_demand_report": self.generate_demand_report,
        }

    def tool_specs(self) -> dict[str, ToolSpec]:
        return dict(DEMAND_IMPACT_TOOL_SPECS)

    def available_next_tools(self) -> list[str]:
        sequence = [
            ("demand_plan_json", "prepare_demand_plan"),
            ("reference_json", "run_reference_demand_simulation"),
            ("adjusted_json", "run_adjusted_demand_simulation"),
            ("demand_comparison_json", "compare_demand_impact"),
            ("demand_report_json", "generate_demand_report"),
        ]
        for artifact, tool_name in sequence:
            if not self.paths[artifact].exists():
                return [tool_name]
        return []

    def state_snapshot(self) -> dict:
        available = self.available_next_tools()
        snapshot = {
            "request_text": self.request_text,
            "scenario": self.scenario,
            "scenario_runtime": self.runtime.as_dict(),
            "duration_seconds": self.duration_seconds,
            "task_route": self.task_route,
            "available_next_tools": available,
            "completed_tools": [run["tool_name"] for run in self.runs if run.get("ok")],
            "failed_tools": [run["tool_name"] for run in self.runs if not run.get("ok")],
            "run_root": str(self.run_root),
        }
        for key, path in self.paths.items():
            snapshot[key] = str(path) if path.exists() else None
        if self.paths["demand_plan_json"].exists():
            snapshot["demand_plan"] = load_json(self.paths["demand_plan_json"])
        if self.paths["demand_comparison_json"].exists():
            snapshot["comparison"] = load_json(self.paths["demand_comparison_json"])
        snapshot["available_tool_specs"] = [
            DEMAND_IMPACT_TOOL_SPECS[name].as_dict(snapshot) for name in available
        ]
        snapshot["tool_catalog"] = [spec.as_dict(snapshot) for spec in DEMAND_IMPACT_TOOL_SPECS.values()]
        return snapshot

    def prepare_demand_plan(self, duration_seconds: int | None = None) -> ToolResult:
        if duration_seconds is not None:
            self.duration_seconds = duration_seconds
        run = self._run_python_module(
            "prepare_demand_plan",
            "交通需求方案生成脚本",
            "simtrend_app.tool_scripts.build_demand_plan",
            [
                "--request-text",
                self.request_text,
                "--duration-seconds",
                str(self.duration_seconds),
                "--project-dir",
                str(self.project_dir),
                "--output",
                str(self.paths["demand_plan_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)
        plan = load_json(self.paths["demand_plan_json"])
        profile = plan["adjusted_profile"]
        multiplier = float(profile.get("target_multiplier", profile.get("multiplier", 1.0)) or 1.0)
        scope = plan.get("adjustment_scope") or {}
        return ToolResult(
            ok=True,
            message=(
                f"已生成需求评估方案：{scope.get('spatial_scope_label', '整个场景')}，"
                f"第 {scope.get('time_window_start_s', 0)}-{scope.get('time_window_end_s', plan['duration_seconds'])} 秒，"
                f"{plan['target_label']}调整为 {multiplier:.2f} 倍。"
            ),
            data={"demand_plan": plan, "run_root": str(self.run_root), "runs": list(self.runs)},
        )

    def run_reference_demand_simulation(self) -> ToolResult:
        return self._run_demand_variant("reference")

    def run_adjusted_demand_simulation(self) -> ToolResult:
        return self._run_demand_variant("adjusted")

    def _run_demand_variant(self, variant: str) -> ToolResult:
        is_reference = variant == "reference"
        tool_name = "run_reference_demand_simulation" if is_reference else "run_adjusted_demand_simulation"
        label = "原始需求仿真脚本" if is_reference else "调整后需求仿真脚本"
        output_dir = self.reference_dir if is_reference else self.adjusted_dir
        output_json = self.paths["reference_json" if is_reference else "adjusted_json"]
        run = self._run_python_module(
            tool_name,
            label,
            "simtrend_app.tool_scripts.run_demand_simulation",
            [
                "--project-dir",
                str(self.project_dir),
                "--demand-plan-json",
                str(self.paths["demand_plan_json"]),
                "--variant",
                variant,
                "--output-dir",
                str(output_dir),
                "--output",
                str(output_json),
            ],
        )
        if not run["ok"]:
            return self._failure(run)
        payload = load_json(output_json)
        return ToolResult(
            ok=True,
            message=f"{payload['variant_label']}仿真已完成，返回码为 {payload['run']['returncode']}。",
            data={f"{variant}_run": payload["run"], "runs": list(self.runs)},
        )

    def compare_demand_impact(self) -> ToolResult:
        run = self._run_python_module(
            "compare_demand_impact",
            "交通需求影响对比脚本",
            "simtrend_app.tool_scripts.compare_demand_impact",
            [
                "--demand-plan-json",
                str(self.paths["demand_plan_json"]),
                "--reference-json",
                str(self.paths["reference_json"]),
                "--adjusted-json",
                str(self.paths["adjusted_json"]),
                "--output",
                str(self.paths["demand_comparison_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)
        payload = load_json(self.paths["demand_comparison_json"])
        comparison = payload["comparison"]
        return ToolResult(
            ok=True,
            message=(
                "已完成需求影响对比。"
                f"全网平均等待变化 {comparison['overall_avg_wait_delta_s']:+.2f} 秒，"
                f"完成车辆数变化 {comparison['arrived_delta']:+.0f} 辆。"
            ),
            data={
                "workflow_type": "demand_impact_evaluation",
                "comparison": comparison,
                "impact_note": payload["impact_note"],
                "runs": list(self.runs),
            },
        )

    def generate_demand_report(self) -> ToolResult:
        run = self._run_python_module(
            "generate_demand_report",
            "需求影响报告生成脚本",
            "simtrend_app.tool_scripts.generate_demand_report",
            [
                "--demand-plan-json",
                str(self.paths["demand_plan_json"]),
                "--comparison-json",
                str(self.paths["demand_comparison_json"]),
                "--output",
                str(self.paths["demand_report_json"]),
            ],
        )
        if not run["ok"]:
            return self._failure(run)

        plan = load_json(self.paths["demand_plan_json"])
        reference = load_json(self.paths["reference_json"])
        adjusted = load_json(self.paths["adjusted_json"])
        comparison_payload = load_json(self.paths["demand_comparison_json"])
        report = load_json(self.paths["demand_report_json"])
        simulation_runs = [reference["run"], adjusted["run"]]
        message = (
            report["human_message"]
            + "\n\n工具链日志：\n"
            + format_runs(self.runs)
            + "\n\nSimTrend Engine 命令日志：\n"
            + format_runs(simulation_runs)
        )
        return ToolResult(
            ok=True,
            message=message,
            data={
                "workflow_type": "demand_impact_evaluation",
                "scenario": self.scenario,
                "scenario_runtime": self.runtime.as_dict(),
                "duration_seconds": plan["duration_seconds"],
                "demand_plan": plan,
                "target_label": plan["target_label"],
                "reference": comparison_payload["reference_metrics"],
                "adjusted": comparison_payload["adjusted_metrics"],
                "baseline": comparison_payload["reference_metrics"],
                "optimized": comparison_payload["adjusted_metrics"],
                "comparison": comparison_payload["comparison"],
                "edge_impacts": comparison_payload.get("edge_impacts", []),
                "edge_impact_summary": comparison_payload.get("edge_impact_summary", {}),
                "impact_note": comparison_payload["impact_note"],
                "tradeoff_note": comparison_payload["impact_note"],
                "controlled_variables": report["controlled_variables"],
                "changed_variable": report["changed_variable"],
                "adjustment_scope": report.get("adjustment_scope", plan.get("adjustment_scope", {})),
                "demand_adjustments": comparison_payload["demand_adjustments"],
                "pickup_waiting": comparison_payload["pickup_waiting"],
                "reference_cfg_file": reference["cfg_file"],
                "adjusted_cfg_file": adjusted["cfg_file"],
                "baseline_cfg_file": reference["cfg_file"],
                "optimized_cfg_file": adjusted["cfg_file"],
                "animations": {
                    "reference": reference.get("animation", {}),
                    "adjusted": adjusted.get("animation", {}),
                    "baseline": reference.get("animation", {}),
                    "optimized": adjusted.get("animation", {}),
                },
                "tool_chain_steps": report["tool_chain_steps"],
                "run_root": str(self.run_root),
                "runs": list(self.runs),
                "simulation_runs": simulation_runs,
                "extra": {},
            },
        )

    def _run_python_module(
        self,
        tool_name: str,
        label: str,
        module_name: str,
        module_args: list[str],
    ) -> dict:
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
            message=f"{run['label']}执行失败。\n\n工具链日志：\n{format_runs(self.runs)}",
            data={
                "run_root": str(self.run_root),
                "runs": list(self.runs),
                "tool_chain_steps": [item["tool_name"] for item in self.runs],
            },
        )
