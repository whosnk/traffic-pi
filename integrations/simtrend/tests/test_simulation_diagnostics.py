import json
from pathlib import Path

from simtrend_app.agent.task_router import TaskRouter
from simtrend_app.config import Settings
from simtrend_app.simulation_diagnostics import diagnose_simulation_result


def _settings(project_dir: Path) -> Settings:
    return Settings(
        qwen_api_key="",
        qwen_base_url="https://api.deepseek.com",
        qwen_model="deepseek-v4-flash",
        sumo_project_dir=str(project_dir),
        debug=False,
        public_demo=False,
        single_visitor=False,
        visitor_lock_ttl_seconds=1800,
    )


def _write_diagnostic_fixture(project_dir: Path) -> None:
    network_dir = project_dir / "network"
    run_root = project_dir / "outputs" / "agent_runs" / "latest_run"
    json_dir = run_root / "json"
    adjusted_dir = run_root / "adjusted_demand"
    network_dir.mkdir(parents=True)
    json_dir.mkdir(parents=True)
    adjusted_dir.mkdir(parents=True)
    (project_dir / "scenario.json").write_text(
        json.dumps({"id": "diagnostic_test", "name": "诊断测试场景"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (network_dir / "intersection.net.xml").write_text(
        """<net>
        <edge id="road_a" name="北广场入口"><lane id="road_a_0"/></edge>
        <edge id="road_b" name="外围道路"><lane id="road_b_0"/></edge>
        <connection from="road_a" to="road_b"/>
        </net>""",
        encoding="utf-8",
    )
    (adjusted_dir / "edge_metrics.xml").write_text(
        """<meandata><interval begin="0" end="600">
        <edge id="road_a" sampledSeconds="200" entered="10" left="5" speed="3" density="12" waitingTime="100" timeLoss="100"/>
        <edge id="road_b" sampledSeconds="200" entered="15" left="15" speed="12" density="2" waitingTime="0" timeLoss="10"/>
        </interval></meandata>""",
        encoding="utf-8",
    )
    (adjusted_dir / "statistics.xml").write_text(
        '<statistics><vehicles inserted="20" running="2"/>'
        '<vehicleTripStatistics waitingTime="8" timeLoss="12" count="18"/></statistics>',
        encoding="utf-8",
    )
    (adjusted_dir / "summary.xml").write_text(
        '<summary><step time="0" arrived="0" halting="1"/>'
        '<step time="600" arrived="18" halting="4"/></summary>',
        encoding="utf-8",
    )
    (adjusted_dir / "tripinfo.xml").write_text("<tripinfos/>", encoding="utf-8")
    (adjusted_dir / "queue.xml").write_text("<queue-export/>", encoding="utf-8")
    result = {
        "variant": "adjusted",
        "duration_seconds": 600,
        "edge_metrics_file": str(adjusted_dir / "edge_metrics.xml"),
        "outputs": {
            key: str(adjusted_dir / f"{key}.xml")
            for key in ("statistics", "summary", "tripinfo", "queue")
        },
        "run": {"ok": True, "returncode": 0},
    }
    (json_dir / "adjusted_demand_result.json").write_text(
        json.dumps(result, ensure_ascii=False),
        encoding="utf-8",
    )


def test_diagnosis_ranks_bottleneck_and_returns_spatial_selection(tmp_path) -> None:
    _write_diagnostic_fixture(tmp_path)

    result = diagnose_simulation_result(_settings(tmp_path), variant="latest", top_n=2)

    assert result.ok
    diagnosis = result.data["diagnosis"]
    assert diagnosis["summary"]["primary_bottleneck"] == "北广场入口"
    assert diagnosis["bottlenecks"][0]["edge_id"] == "road_a"
    assert diagnosis["bottlenecks"][0]["severity"] == "高"
    assert "停车等待偏高" in diagnosis["bottlenecks"][0]["anomaly_types"]
    assert diagnosis["overall_metrics"]["arrived_vehicle_count"] == 18
    assert result.data["spatial_selection"]["edge_id"] == "road_a"
    output = Path(result.data["diagnosis_json"])
    assert output.is_file()
    assert output.parent == tmp_path / "outputs/agent_runs/latest_run/json"
    again = diagnose_simulation_result(_settings(tmp_path), variant="latest", top_n=1)
    assert Path(again.data["diagnosis_json"]) != output
    assert output.is_file()
    assert "不重新运行" not in result.message


def test_diagnosis_returns_recoverable_error_without_previous_run(tmp_path) -> None:
    result = diagnose_simulation_result(_settings(tmp_path))

    assert not result.ok
    assert result.data["error"]["code"] == "DIAGNOSIS_INPUT_NOT_FOUND"
    assert result.data["error"]["recoverable"]


def test_router_sends_latest_result_diagnosis_to_read_only_tool() -> None:
    route = TaskRouter().route("请诊断最近一次仿真结果，哪里是主要交通瓶颈？")

    assert route.task_type == "simulation_diagnosis"
    assert route.workflow == "simulation_diagnosis"


def test_router_keeps_run_and_diagnose_request_in_simulation_workflow() -> None:
    route = TaskRouter().route("请运行仿真并诊断拥堵瓶颈")

    assert route.task_type != "simulation_diagnosis"
