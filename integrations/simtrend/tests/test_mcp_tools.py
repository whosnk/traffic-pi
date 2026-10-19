import json
from pathlib import Path

from simtrend_app.config import Settings
from simtrend_app.mcp_tools import SimTrendMCPService
from simtrend_app.tools.base import ToolResult


def _settings(project: Path) -> Settings:
    return Settings("", "", "", str(project), True, False, False, 1800)


def _scenario_root(tmp_path: Path) -> Path:
    root = tmp_path / "scenarios"
    project = root / "demo"
    project.mkdir(parents=True)
    (project / "scenario.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "演示场景",
                "description": "MCP 测试场景",
                "supported_capabilities": ["路网查询", "信号优化"],
                "intersections": [{"id": "j0", "name": "测试路口"}],
                "map": {"enabled": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def test_mcp_service_lists_portable_scenario_metadata(tmp_path) -> None:
    root = _scenario_root(tmp_path)
    service = SimTrendMCPService(_settings(root / "demo"), root)

    result = service.list_scenarios()

    assert result["ok"]
    assert result["scenarios"][0]["scenario_id"] == "demo"
    assert result["scenarios"][0]["map_enabled"]
    assert "project_dir" not in result["scenarios"][0]


def test_mcp_capability_catalog_keeps_business_and_atomic_layers_separate(tmp_path) -> None:
    root = _scenario_root(tmp_path)
    service = SimTrendMCPService(_settings(root / "demo"), root)

    result = service.get_capabilities("demo")

    workflow_names = {item["name"] for item in result["workflows"]}
    atomic_names = {item["name"] for item in result["internal_atomic_tools"]}
    assert "run_incident_signal_optimization" in workflow_names
    assert "run_demand_impact_evaluation" in workflow_names
    assert "detect_incident" in atomic_names
    assert "run_baseline_simulation" in atomic_names


def test_mcp_service_rejects_unknown_scenario_with_structured_error(tmp_path) -> None:
    root = _scenario_root(tmp_path)
    service = SimTrendMCPService(_settings(root / "demo"), root)

    result = service.query_signal_control("missing")

    assert not result["ok"]
    assert result["error"]["code"] == "MCP_TOOL_EXECUTION_FAILED"
    assert "demo" in result["message"]


def test_mcp_workflow_stops_at_failed_step_and_returns_trace(tmp_path, monkeypatch) -> None:
    root = _scenario_root(tmp_path)
    project = root / "demo"

    class FakeChain:
        def __init__(self, *args, **kwargs) -> None:
            self.run_root = project / "outputs" / "agent_runs" / "run_1"

        def detect_incident(self) -> ToolResult:
            return ToolResult(True, "识别成功")

        def build_signal_plan(self, **kwargs) -> ToolResult:
            return ToolResult(False, "配时失败", {"error": {"code": "INVALID_SIGNAL_PLAN"}})

        def analyze_closure_impact(self) -> ToolResult:
            raise AssertionError("失败后不应继续")

        run_baseline_simulation = analyze_closure_impact
        run_optimized_simulation = analyze_closure_impact
        compare_metrics = analyze_closure_impact
        generate_report = analyze_closure_impact

    monkeypatch.setattr("simtrend_app.mcp_tools.AgentToolChain", FakeChain)
    service = SimTrendMCPService(_settings(project), root)
    service.repo_root = root.parent

    result = service.run_incident_signal_optimization(
        "demo",
        "东北路口东进口发生追尾事故，持续10分钟，封闭1条车道",
    )

    assert not result["ok"]
    assert result["failed_step"] == "build_signal_plan"
    assert [item["tool"] for item in result["steps"]] == ["detect_incident", "build_signal_plan"]
    assert result["run_root"].endswith("outputs/agent_runs/run_1")


def test_mcp_incident_workflow_requires_precise_location_before_start(tmp_path, monkeypatch) -> None:
    root = _scenario_root(tmp_path)
    service = SimTrendMCPService(_settings(root / "demo"), root)

    def fail_if_constructed(*args, **kwargs):
        raise AssertionError("澄清完成前不应创建仿真工具链")

    monkeypatch.setattr("simtrend_app.mcp_tools.AgentToolChain", fail_if_constructed)

    result = service.run_incident_signal_optimization(
        "demo",
        "东进口发生追尾事故，请进行信号优化仿真",
    )

    assert not result["ok"]
    assert result["status"] == "clarification_required"
    assert "具体路口位置" in result["missing_fields"]
    assert not result["simulation_started"]


def test_mcp_result_removes_private_commands_and_makes_paths_portable(tmp_path) -> None:
    root = _scenario_root(tmp_path)
    service = SimTrendMCPService(_settings(root / "demo"), root)
    artifact = service.repo_root / "simtrend_scenarios" / "demo" / "outputs" / "result.json"
    result = ToolResult(
        True,
        f"结果位于 {service.repo_root}",
        {
            "command": ["python", "run.py"],
            "result_json": str(artifact),
            "project_dir": str(root / "demo"),
        },
    )

    payload = service._tool_result_payload(result, scenario_id="demo")

    assert "command" not in payload["data"]
    assert "project_dir" not in payload["data"]
    assert payload["data"]["result_json"] == "simtrend_scenarios/demo/outputs/result.json"
    assert str(service.repo_root) not in payload["message"]
