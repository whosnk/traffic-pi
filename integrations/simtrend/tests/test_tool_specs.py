from simtrend_app.config import Settings
from simtrend_app.tools.base import ToolResult
from simtrend_app.tools.registry import ToolRegistry
from simtrend_app.tools.specs import (
    DEMAND_IMPACT_TOOL_SPECS,
    FAIR_SIMULATION_COMPARISON_TOOL_SPEC,
    NETWORK_QUERY_TOOL_SPEC,
    PARAMETERIZED_SIGNAL_TOOL_SPEC,
    SIGNAL_OPTIMIZATION_TOOL_SPECS,
    SIGNAL_CONTROL_QUERY_TOOL_SPEC,
    SIMULATION_DIAGNOSIS_TOOL_SPEC,
    ToolSpec,
)


def _settings() -> Settings:
    return Settings(
        qwen_api_key="",
        qwen_base_url="https://api.deepseek.com",
        qwen_model="deepseek-v4-flash",
        sumo_project_dir="simtrend_scenarios/four_intersections",
        debug=False,
        public_demo=False,
        single_visitor=False,
        visitor_lock_ttl_seconds=1800,
    )


def test_signal_optimization_specs_expose_complete_dependency_chain() -> None:
    specs = SIGNAL_OPTIMIZATION_TOOL_SPECS

    assert list(specs) == [
        "detect_incident",
        "build_signal_plan",
        "analyze_closure_impact",
        "run_baseline_simulation",
        "run_optimized_simulation",
        "compare_metrics",
        "generate_report",
    ]
    assert specs["build_signal_plan"].required_artifacts == ("detection_json",)
    assert specs["analyze_closure_impact"].required_artifacts == ("signal_plan_json",)
    assert specs["run_baseline_simulation"].required_artifacts == (
        "signal_plan_json",
        "closure_analysis_json",
    )
    assert specs["run_optimized_simulation"].required_artifacts == (
        "signal_plan_json",
        "baseline_json",
    )
    assert specs["generate_report"].required_artifacts == (
        "comparison_json",
        "closure_analysis_json",
    )
    assert "SIMULATION_FAILED" in specs["run_baseline_simulation"].possible_errors


def test_network_query_uses_the_same_tool_contract_format() -> None:
    payload = NETWORK_QUERY_TOOL_SPEC.as_dict()

    assert payload["name"] == "query_network_knowledge"
    assert payload["category"] == "network_query"
    assert payload["input_schema"]["required"] == ["query"]
    assert payload["read_only"]
    assert payload["produces_artifacts"] == ["spatial_selection"]


def test_simulation_diagnosis_has_independent_analysis_contract() -> None:
    payload = SIMULATION_DIAGNOSIS_TOOL_SPEC.as_dict()

    assert payload["name"] == "diagnose_simulation_result"
    assert payload["category"] == "analysis"
    assert payload["input_schema"]["properties"]["top_n"]["maximum"] == 10
    assert payload["produces_artifacts"] == ["diagnosis_json", "spatial_selection"]


def test_parameterized_signal_tool_requires_controller_and_complete_phase_array() -> None:
    payload = PARAMETERIZED_SIGNAL_TOOL_SPEC.as_dict()

    assert payload["name"] == "evaluate_signal_plan"
    assert payload["category"] == "simulation"
    assert payload["input_schema"]["required"] == ["controller_id", "phase_durations"]
    assert payload["input_schema"]["properties"]["random_seed"]["maximum"] == 2147483647
    assert "SIMULATION_FAILED" in payload["possible_errors"]


def test_signal_control_query_is_read_only_and_returns_reusable_context() -> None:
    payload = SIGNAL_CONTROL_QUERY_TOOL_SPEC.as_dict()

    assert payload["name"] == "query_signal_control"
    assert payload["category"] == "network_query"
    assert payload["read_only"]
    assert payload["produces_artifacts"] == ["signal_context", "spatial_selection"]


def test_fair_comparison_tool_requires_two_result_selectors() -> None:
    payload = FAIR_SIMULATION_COMPARISON_TOOL_SPEC.as_dict()

    assert payload["name"] == "compare_simulation_runs"
    assert payload["category"] == "analysis"
    assert payload["input_schema"]["required"] == ["reference", "candidate"]
    assert payload["read_only"]
    assert payload["produces_artifacts"] == ["fair_comparison_json", "spatial_selection"]


def test_demand_impact_specs_form_an_independent_dependency_chain() -> None:
    specs = DEMAND_IMPACT_TOOL_SPECS

    assert list(specs) == [
        "prepare_demand_plan",
        "run_reference_demand_simulation",
        "run_adjusted_demand_simulation",
        "compare_demand_impact",
        "generate_demand_report",
    ]
    assert specs["run_reference_demand_simulation"].required_artifacts == ("demand_plan_json",)
    assert specs["run_adjusted_demand_simulation"].required_artifacts == (
        "demand_plan_json",
        "reference_json",
    )
    assert specs["compare_demand_impact"].required_artifacts == (
        "demand_plan_json",
        "reference_json",
        "adjusted_json",
    )


def test_registry_rejects_tool_when_precondition_is_missing() -> None:
    called = False

    def handler() -> ToolResult:
        nonlocal called
        called = True
        return ToolResult(ok=True, message="should not run")

    spec = ToolSpec(
        name="dependent_tool",
        display_name="依赖工具",
        description="测试前置条件",
        category="test",
        required_artifacts=("input_json",),
    )
    registry = ToolRegistry(
        _settings(),
        tool_overrides={"dependent_tool": handler},
        tool_specs={"dependent_tool": spec},
    )

    result = registry.run("dependent_tool", {}, state={"input_json": None})

    assert not result.ok
    assert not called
    assert result.data["error"]["code"] == "PRECONDITION_FAILED"
    assert result.data["error"]["missing_artifacts"] == ["input_json"]


def test_registry_validates_input_schema_before_execution() -> None:
    called = False

    def handler(duration_seconds: int) -> ToolResult:
        nonlocal called
        called = True
        return ToolResult(ok=True, message=str(duration_seconds))

    spec = ToolSpec(
        name="duration_tool",
        display_name="时长工具",
        description="测试输入校验",
        category="test",
        input_schema={
            "type": "object",
            "properties": {
                "duration_seconds": {"type": "integer", "minimum": 60, "maximum": 3600}
            },
            "required": ["duration_seconds"],
        },
    )
    registry = ToolRegistry(
        _settings(),
        tool_overrides={"duration_tool": handler},
        tool_specs={"duration_tool": spec},
    )

    result = registry.run("duration_tool", {"duration_seconds": 30}, state={})

    assert not result.ok
    assert not called
    assert result.data["error"]["code"] == "INVALID_TOOL_INPUT"


def test_registry_catalog_marks_available_tools_from_state() -> None:
    registry = ToolRegistry(
        _settings(),
        tool_overrides={"build_signal_plan": lambda: ToolResult(ok=True, message="ok")},
        tool_specs={"build_signal_plan": SIGNAL_OPTIMIZATION_TOOL_SPECS["build_signal_plan"]},
    )

    unavailable = registry.available_tool_specs(["build_signal_plan"], state={})[0]
    available = registry.available_tool_specs(
        ["build_signal_plan"],
        state={"detection_json": "detection.json"},
    )[0]

    assert not unavailable["available"]
    assert unavailable["unmet_preconditions"] == ["detection_json"]
    assert available["available"]
    assert available["unmet_preconditions"] == []
