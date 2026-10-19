from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from simtrend_app.config import Settings, get_settings
from simtrend_app.agent.intent_parser import build_structured_prompt
from simtrend_app.fair_simulation_comparison import compare_simulation_runs
from simtrend_app.network_query import NetworkQueryService
from simtrend_app.parameterized_signal import evaluate_signal_plan
from simtrend_app.scenarios import Scenario, load_scenarios
from simtrend_app.signal_control_query import query_signal_control
from simtrend_app.simulation_diagnostics import diagnose_simulation_result
from simtrend_app.task_safety import review_task_intent
from simtrend_app.tools.agent_tool_chain import AgentToolChain
from simtrend_app.tools.base import ToolResult
from simtrend_app.tools.demand_impact_tool_chain import DemandImpactToolChain
from simtrend_app.tools.specs import (
    DEMAND_IMPACT_TOOL_SPECS,
    FAIR_SIMULATION_COMPARISON_TOOL_SPEC,
    NETWORK_QUERY_TOOL_SPEC,
    PARAMETERIZED_SIGNAL_TOOL_SPEC,
    SIGNAL_CONTROL_QUERY_TOOL_SPEC,
    SIGNAL_OPTIMIZATION_TOOL_SPECS,
    SIMULATION_DIAGNOSIS_TOOL_SPEC,
)


_PRIVATE_RESULT_KEYS = {
    "build_net_script",
    "command",
    "gui_script",
    "project_dir",
    "sumo_binary",
    "sumo_project_dir",
    "train_script",
}


class SimTrendMCPService:
    """Transport-independent facade used by the MCP server and tests."""

    def __init__(
        self,
        settings: Settings | None = None,
        scenario_root: str | Path | None = None,
    ) -> None:
        self.repo_root = Path(__file__).resolve().parents[1]
        self.settings = settings or get_settings()
        self.scenario_root = Path(scenario_root or self.repo_root / "simtrend_scenarios").resolve()

    def list_scenarios(self) -> dict[str, Any]:
        scenarios = [self._scenario_summary(item) for item in self._scenarios()]
        return {
            "ok": True,
            "status": "success",
            "count": len(scenarios),
            "scenarios": scenarios,
        }

    def get_capabilities(self, scenario_id: str = "") -> dict[str, Any]:
        scenario = self._resolve_scenario(scenario_id) if scenario_id else None
        specs = [
            NETWORK_QUERY_TOOL_SPEC,
            SIGNAL_CONTROL_QUERY_TOOL_SPEC,
            PARAMETERIZED_SIGNAL_TOOL_SPEC,
            SIMULATION_DIAGNOSIS_TOOL_SPEC,
            FAIR_SIMULATION_COMPARISON_TOOL_SPEC,
        ]
        atomic_specs = [*SIGNAL_OPTIMIZATION_TOOL_SPECS.values(), *DEMAND_IMPACT_TOOL_SPECS.values()]
        return {
            "ok": True,
            "status": "success",
            "scenario": self._scenario_summary(scenario) if scenario else None,
            "business_tools": [spec.as_dict() for spec in specs],
            "workflows": [
                {
                    "name": "run_incident_signal_optimization",
                    "description": "事故识别、封道预检、基线仿真、优化仿真、指标对比和报告生成。",
                },
                {
                    "name": "run_demand_impact_evaluation",
                    "description": "生成需求调整方案，运行原始与调整后仿真并比较影响。",
                },
            ],
            "internal_atomic_tools": [spec.as_dict() for spec in atomic_specs],
        }

    def query_network_knowledge(self, scenario_id: str, query: str) -> dict[str, Any]:
        try:
            scenario = self._resolve_scenario(scenario_id)
            result = NetworkQueryService(scenario.runtime()).query(query)
            return {
                "ok": result.status not in {"not_found"},
                "status": result.status,
                "scenario_id": scenario.id,
                "query_kind": result.query_kind,
                "message": result.answer_markdown,
                "candidates": list(result.candidates),
                "spatial_selection": result.spatial_selection,
            }
        except Exception as exc:
            return self._exception_payload(exc, scenario_id=scenario_id)

    def query_signal_control(
        self,
        scenario_id: str,
        query: str = "",
        controller_id: str = "",
        edge_id: str = "",
        lane_id: str = "",
        program_id: str = "0",
    ) -> dict[str, Any]:
        try:
            settings = self._settings_for(scenario_id)
            result = query_signal_control(
                settings,
                query=query,
                controller_id=controller_id or None,
                edge_id=edge_id or None,
                lane_id=lane_id or None,
                program_id=program_id,
            )
            return self._tool_result_payload(result, scenario_id=scenario_id)
        except Exception as exc:
            return self._exception_payload(exc, scenario_id=scenario_id)

    def run_incident_signal_optimization(
        self,
        scenario_id: str,
        incident_text: str,
        duration_seconds: int = 600,
        strategy: str = "signal_optimization",
    ) -> dict[str, Any]:
        try:
            duration = self._duration(duration_seconds)
            safety_review = review_task_intent(
                incident_text,
                [],
                is_follow_up=False,
                task_route={
                    "task_type": "incident_signal_optimization",
                    "workflow": "signal_optimization",
                    "source": "mcp",
                },
            )
            if safety_review.requires_clarification:
                return safety_review.clarification_payload(scenario_id)
            settings = self._settings_for(scenario_id)
            chain = AgentToolChain(
                settings,
                incident_text=incident_text,
                scenario=scenario_id,
                strategy=strategy,
                duration_seconds=duration,
                task_route={
                    "task_type": "incident_signal_optimization",
                    "workflow": "signal_optimization",
                    "source": "mcp",
                },
            )
            steps: list[dict[str, Any]] = []
            calls: list[tuple[str, Callable[..., ToolResult], dict[str, Any]]] = [
                ("detect_incident", chain.detect_incident, {}),
                ("build_signal_plan", chain.build_signal_plan, {"strategy": strategy, "duration_seconds": duration}),
                ("analyze_closure_impact", chain.analyze_closure_impact, {}),
                ("run_baseline_simulation", chain.run_baseline_simulation, {}),
                ("run_optimized_simulation", chain.run_optimized_simulation, {}),
                ("compare_metrics", chain.compare_metrics, {}),
                ("generate_report", chain.generate_report, {"strategy": strategy, "scenario": scenario_id}),
            ]
            return self._run_workflow_calls(scenario_id, chain.run_root, calls, steps)
        except Exception as exc:
            return self._exception_payload(exc, scenario_id=scenario_id)

    def run_demand_impact_evaluation(
        self,
        scenario_id: str,
        request_text: str,
        duration_seconds: int = 600,
    ) -> dict[str, Any]:
        try:
            duration = self._duration(duration_seconds)
            review = review_task_intent(
                request_text, [], is_follow_up=False,
                task_route={"task_type": "demand_adjustment"},
            )
            if review.requires_clarification:
                return review.clarification_payload(scenario_id)
            review.intent.merged_intent["simulation_duration_seconds"] = duration
            request_text = build_structured_prompt(request_text, review.intent)
            settings = self._settings_for(scenario_id)
            chain = DemandImpactToolChain(
                settings,
                request_text=request_text,
                scenario=scenario_id,
                duration_seconds=duration,
                task_route={
                    "task_type": "demand_adjustment",
                    "workflow": "demand_impact_evaluation",
                    "source": "mcp",
                },
            )
            steps: list[dict[str, Any]] = []
            calls: list[tuple[str, Callable[..., ToolResult], dict[str, Any]]] = [
                ("prepare_demand_plan", chain.prepare_demand_plan, {"duration_seconds": duration}),
                ("run_reference_demand_simulation", chain.run_reference_demand_simulation, {}),
                ("run_adjusted_demand_simulation", chain.run_adjusted_demand_simulation, {}),
                ("compare_demand_impact", chain.compare_demand_impact, {}),
                ("generate_demand_report", chain.generate_demand_report, {}),
            ]
            return self._run_workflow_calls(scenario_id, chain.run_root, calls, steps)
        except Exception as exc:
            return self._exception_payload(exc, scenario_id=scenario_id)

    def evaluate_signal_plan(
        self,
        scenario_id: str,
        controller_id: str,
        phase_durations: list[float],
        duration_seconds: int = 600,
        random_seed: int = 42,
        program_id: str = "0",
        render_animation: bool = False,
        result_slot: str = "latest",
    ) -> dict[str, Any]:
        try:
            settings = self._settings_for(scenario_id)
            result = evaluate_signal_plan(
                settings,
                controller_id=controller_id,
                phase_durations=phase_durations,
                duration_seconds=self._duration(duration_seconds),
                random_seed=random_seed,
                program_id=program_id,
                render_animation=render_animation,
                result_slot=result_slot,
            )
            return self._tool_result_payload(result, scenario_id=scenario_id)
        except Exception as exc:
            return self._exception_payload(exc, scenario_id=scenario_id)

    def diagnose_simulation_result(
        self,
        scenario_id: str,
        variant: str = "latest",
        top_n: int = 5,
    ) -> dict[str, Any]:
        try:
            settings = self._settings_for(scenario_id)
            result = diagnose_simulation_result(settings, variant=variant, top_n=top_n)
            return self._tool_result_payload(result, scenario_id=scenario_id)
        except Exception as exc:
            return self._exception_payload(exc, scenario_id=scenario_id)

    def compare_simulation_runs(
        self,
        scenario_id: str,
        reference: str = "reference",
        candidate: str = "candidate",
        top_n: int = 5,
    ) -> dict[str, Any]:
        try:
            settings = self._settings_for(scenario_id)
            result = compare_simulation_runs(
                settings,
                reference=reference,
                candidate=candidate,
                top_n=top_n,
            )
            return self._tool_result_payload(result, scenario_id=scenario_id)
        except Exception as exc:
            return self._exception_payload(exc, scenario_id=scenario_id)

    def _run_workflow_calls(
        self,
        scenario_id: str,
        run_root: Path,
        calls: list[tuple[str, Callable[..., ToolResult], dict[str, Any]]],
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        final_result: ToolResult | None = None
        for name, function, arguments in calls:
            progress = getattr(self, "progress_callback", None)
            if progress:
                progress({"tool": name, "status": "running"})
            result = function(**arguments)
            if progress:
                progress({"tool": name, "status": "completed" if result.ok else "failed", "message": result.message[:500]})
            final_result = result
            steps.append({"tool": name, "ok": result.ok, "message": result.message[:500]})
            if not result.ok:
                payload = self._tool_result_payload(result, scenario_id=scenario_id)
                payload.update(
                    {
                        "failed_step": name,
                        "steps": self._portable_value(steps),
                        "run_root": self._portable_path(run_root),
                    }
                )
                return payload
        if final_result is None:
            raise RuntimeError("工作流没有可执行步骤。")
        payload = self._tool_result_payload(final_result, scenario_id=scenario_id)
        payload.update(
            {"steps": self._portable_value(steps), "run_root": self._portable_path(run_root)}
        )
        return payload

    def _scenarios(self) -> list[Scenario]:
        return load_scenarios(self.scenario_root)

    def _resolve_scenario(self, scenario_id: str) -> Scenario:
        normalized = str(scenario_id or "").strip()
        scenarios = self._scenarios()
        if not normalized:
            if len(scenarios) == 1:
                return scenarios[0]
            available = ", ".join(item.id for item in scenarios)
            raise ValueError(f"必须指定 scenario_id。可用场景：{available or '无'}")
        for scenario in scenarios:
            if scenario.id == normalized:
                return scenario
        available = ", ".join(item.id for item in scenarios)
        raise ValueError(f"未知场景 `{normalized}`。可用场景：{available or '无'}")

    def _settings_for(self, scenario_id: str) -> Settings:
        scenario = self._resolve_scenario(scenario_id)
        # MCP calls use isolated run directories even when the web UI is in debug mode.
        return replace(self.settings, sumo_project_dir=str(scenario.path), debug=False)

    @staticmethod
    def _duration(value: int) -> int:
        duration = int(value)
        if not 60 <= duration <= 3600:
            raise ValueError("duration_seconds 必须在 60 到 3600 之间。")
        return duration

    def _scenario_summary(self, scenario: Scenario) -> dict[str, Any]:
        return {
            "scenario_id": scenario.id,
            "name": scenario.name,
            "description": scenario.description,
            "map_enabled": bool(scenario.map_config.get("enabled")),
            "supported_capabilities": list(scenario.supported_capabilities),
            "intersections": [
                {"id": item.get("id", ""), "name": item.get("name", "")}
                for item in scenario.intersections
            ],
        }

    def _tool_result_payload(self, result: ToolResult, *, scenario_id: str) -> dict[str, Any]:
        return {
            "ok": result.ok,
            "status": "success" if result.ok else "error",
            "scenario_id": scenario_id,
            "message": self._redact_text(result.message),
            "data": self._portable_value(result.data),
        }

    def _exception_payload(self, exc: Exception, *, scenario_id: str = "") -> dict[str, Any]:
        message = self._redact_text(str(exc))
        return {
            "ok": False,
            "status": "error",
            "scenario_id": scenario_id,
            "message": message,
            "error": {
                "code": "MCP_TOOL_EXECUTION_FAILED",
                "message": message,
                "recoverable": True,
            },
        }

    def _portable_value(self, value: Any, *, key: str = "") -> Any:
        if isinstance(value, dict):
            return {
                item_key: self._portable_value(item_value, key=item_key)
                for item_key, item_value in value.items()
                if item_key not in _PRIVATE_RESULT_KEYS
            }
        if isinstance(value, (list, tuple)):
            return [self._portable_value(item, key=key) for item in value]
        if isinstance(value, Path):
            return self._portable_path(value)
        if isinstance(value, str):
            return self._portable_string(value, key=key)
        return value

    def _portable_string(self, value: str, *, key: str) -> str:
        cleaned = self._redact_text(value)
        if not any(token in key.lower() for token in ("file", "path", "dir", "json", "animation", "output")):
            return cleaned
        try:
            path = Path(value)
            if path.is_absolute():
                return self._portable_path(path)
        except (OSError, ValueError):
            pass
        return cleaned

    def _portable_path(self, value: str | Path) -> str:
        path = Path(value)
        try:
            return path.resolve().relative_to(self.repo_root).as_posix()
        except (OSError, ValueError):
            return path.name

    def _redact_text(self, value: str) -> str:
        return str(value).replace(str(self.repo_root), ".").replace(str(self.repo_root).replace("\\", "/"), ".")
