import json
from pathlib import Path
import pytest

from simtrend_app import integration as api
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.parameterized_signal import _prepare_run_root
from simtrend_app.fair_simulation_comparison import resolve_simulation_result


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "JOBS", tmp_path / "jobs")
    return tmp_path


def test_map_has_real_lane_membership_and_no_fake_geography_claim():
    four = api.map_data("four_intersections")
    nanjing = api.map_data("nanjing_south_ride_hailing")
    assert four["synthetic"] is True
    assert nanjing["synthetic"] is False
    assert len(four["edges"]) == 24
    assert len(nanjing["edges"]) > 500
    assert len(nanjing["zones"]) == 2
    for edge in four["edges"]:
        assert four["lanes"][edge["edge_id"]]


def test_incident_selection_is_validated_and_preserved():
    _, args = api.prepare_form({
        "scenario_id": "four_intersections", "task": "incident",
        "selection": {"edge_id": "e0_c10", "lane_id": "e0_c10_1"},
        "form": {"location_name": "东北路口东进口", "duration_seconds": 60},
    })
    assert "地图车道ID：e0_c10_1" in args["incident_text"]
    assert "地图道路全部车道：e0_c10_0,e0_c10_1,e0_c10_2" in args["incident_text"]
    with pytest.raises(ValueError):
        api.spatial_context("four_intersections", {"edge_id": "e0_c10", "lane_id": "w0_c00_0"})


def test_no_missing_scenario_silently_runs():
    with pytest.raises(ValueError):
        api.create_job("query_network_knowledge", {"scenario_id": "missing", "query": "test"})


def test_dispatch_rejects_arbitrary_methods_and_file_reads():
    with pytest.raises(ValueError):
        api.validate_call("_settings_for", {})
    with pytest.raises(ValueError):
        api.validate_call("compare_simulation_runs", {
            "scenario_id": "four_intersections", "reference": str(api.ROOT / ".env"), "candidate": "candidate",
        })


def test_job_id_cannot_escape_runtime_directory(jobs):
    with pytest.raises(ValueError):
        api.read_job("../../.env")


def test_query_records_result_and_can_be_recovered(jobs):
    result = api.execute("query_network_knowledge", {"scenario_id": "four_intersections", "query": "有哪些路口"})
    assert result["ok"]
    assert result["type"] == "simtrend-result"
    job = api.read_job(result["job_id"])
    assert job["status"] == "completed"
    assert job["result"] == result
    assert "pid" not in api.public_job(job)


def test_incomplete_incident_is_clarification_not_success(jobs):
    result = api.execute("run_incident_signal_optimization", {
        "scenario_id": "four_intersections", "incident_text": "东进口发生追尾事故",
    })
    assert result["status"] == "clarification_required"
    assert result["simulation_started"] is False
    assert api.read_job(result["job_id"])["status"] == "clarification_required"


def test_sessions_have_separate_histories(jobs):
    for session in ("one", "two"):
        api.create_job("query_network_knowledge", {"scenario_id": "four_intersections", "query": "test"}, session)
    result = api.bridge({"action": "jobs", "session_id": "one"})
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["session_id"] == "one"


def test_parameterized_runs_preserve_prior_files(tmp_path):
    runtime = ScenarioRuntime.from_project_dir(tmp_path)
    before = _prepare_run_root(runtime, "reference")
    marker = before / "keep.txt"
    marker.write_text("retained", encoding="utf-8")
    after = _prepare_run_root(runtime, "reference")
    assert before != after and marker.read_text(encoding="utf-8") == "retained"
    result = after / "json" / "parameterized_result.json"
    result.parent.mkdir()
    result.write_text(json.dumps({"run": {"ok": True}}), encoding="utf-8")
    assert resolve_simulation_result(runtime, "reference") == result


def test_artifacts_require_manifest_entry(jobs):
    job = api.create_job("query_network_knowledge", {"scenario_id": "four_intersections", "query": "test"})
    with pytest.raises(ValueError):
        api.bridge({"action": "artifact", "job_id": job["id"], "artifact_id": "../../.env"})


def test_demand_mcp_and_form_share_normalization(monkeypatch):
    from simtrend_app import mcp_tools
    from simtrend_app.tool_scripts.common import infer_demand_profile
    captured = {}

    class Chain:
        run_root = api.ROOT

        def __init__(self, settings, **kwargs):
            captured.update(kwargs)

        def __getattr__(self, name):
            return lambda **kwargs: None

    monkeypatch.setattr(mcp_tools, "DemandImpactToolChain", Chain)
    service = mcp_tools.SimTrendMCPService()
    monkeypatch.setattr(service, "_run_workflow_calls", lambda *args: {"ok": True})
    for text in ("把南京南站网约车到站流量提高30%，运行仿真并进行对比",
                 "在整个场景将网约车到站流量提高30%，仿真60秒，并与原始需求进行公平对比"):
        assert service.run_demand_impact_evaluation("nanjing_south_ride_hailing", text, 60)["ok"]
        profile = infer_demand_profile(captured["request_text"])
        assert profile["target"] == "ride_hailing_in"
        assert profile["vehicle_multipliers"]["ride_hailing_in"] == 1.3


def test_road_selection_does_not_emit_empty_lane():
    context = api.spatial_context("four_intersections", {"edge_id": "e0_c10"})
    assert "地图车道ID" not in context
    with pytest.raises(ValueError, match="车道数"):
        api.prepare_form({"scenario_id": "four_intersections", "task": "incident",
                          "selection": {"edge_id": "e0_c10"}, "form": {"lane_closure_count": 4}})


def test_interrupted_worker_does_not_stay_running(jobs, monkeypatch):
    job = api.create_job("query_network_knowledge", {"scenario_id": "four_intersections", "query": "test"})
    job.update(status="running", pid=123)
    api.write_job(job)
    monkeypatch.setattr(api, "process_alive", lambda pid: False)
    recovered = api.read_job(job["id"])
    assert recovered["status"] == "failed"
    assert recovered["result"]["status"] == "interrupted"


def test_duration_matches_public_contract():
    from simtrend_app.tool_scripts.common import normalize_duration
    assert normalize_duration(3600) == 3600
