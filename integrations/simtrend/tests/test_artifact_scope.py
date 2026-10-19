import json
from types import SimpleNamespace

import pytest

from simtrend_app import integration as api


@pytest.fixture
def runtime_files(tmp_path, monkeypatch):
    allowed = tmp_path / "simtrend_scenarios" / "scenario" / "outputs" / "agent_runs"
    current = allowed / "current"
    for directory, names in {
        "current/baseline": ["baseline_replay.gif", "baseline.sumocfg"],
        "current/optimized": ["optimized_replay.gif"],
        "current/json": ["report.json"],
        "old/baseline": ["baseline_replay.gif"],
        "old/optimized": ["optimized_replay.gif"],
        "parameterized_reference/simulation": ["parameterized_replay.gif"],
        "parameterized_candidate/simulation": ["parameterized_replay.gif"],
        "current_other/simulation": ["parameterized_replay.gif"],
    }.items():
        folder = allowed / directory
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / name).write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(api, "ROOT", tmp_path)
    monkeypatch.setattr(api, "JOBS", tmp_path / "jobs")
    scenario = SimpleNamespace(runtime=lambda: SimpleNamespace(agent_runs_dir=allowed))
    monkeypatch.setattr(api.SimTrendMCPService, "_resolve_scenario", lambda self, scene_id: scenario)
    return allowed, current


def test_current_run_does_not_collect_other_runs_from_runtime_metadata(runtime_files):
    allowed, current = runtime_files
    result = {"run_root": str(current), "data": {
        "scenario_runtime": {"agent_runs_dir": str(allowed)},
        "old_file": str(allowed / "old/baseline/baseline_replay.gif"),
        "animations": {"baseline": {"gif_file": str(current / "baseline/baseline_replay.gif")}},
    }}
    job = {"id": "a" * 32, "arguments": {"scenario_id": "scenario"}, "artifacts": []}
    api.collect_artifacts(result, job)
    assert len([item for item in job["artifacts"] if item["kind"] == "replay"]) == 2
    assert len(job["artifacts"]) == 4
    assert all((api.ROOT / value).is_relative_to(current) for value in job["artifact_paths"].values())
    api.collect_artifacts(result, job)
    assert len(job["artifacts"]) == 4


def test_single_plan_keeps_its_explicit_replay_without_scanning_parent(runtime_files):
    allowed, _ = runtime_files
    result = {"data": {"scenario_runtime": {"agent_runs_dir": str(allowed)},
                       "animation": {"gif_file": str(allowed / "parameterized_reference/simulation/parameterized_replay.gif")}}}
    job = {"id": "b" * 32, "arguments": {"scenario_id": "scenario"}, "artifacts": []}
    api.collect_artifacts(result, job)
    assert len(job["artifacts"]) == 1


def test_comparison_keeps_explicit_files_from_two_source_runs(runtime_files):
    allowed, current = runtime_files
    result = {"data": {"reference": str(current / "json/report.json"),
                       "candidate": str(allowed / "parameterized_candidate/simulation/parameterized_replay.gif")}}
    job = {"id": "c" * 32, "arguments": {"scenario_id": "scenario"}, "artifacts": []}
    api.collect_artifacts(result, job)
    assert len(job["artifacts"]) == 2


def test_old_job_is_filtered_without_renumbering_urls_or_deleting_files(runtime_files):
    allowed, current = runtime_files
    old_file = allowed / "old/baseline/baseline_replay.gif"
    paths = {"0": old_file, "4": current / "baseline/baseline_replay.gif", "16": current / "optimized/optimized_replay.gif"}
    artifacts = [{"id": key, "kind": "replay", "url": f"/api/simtrend/artifacts/{'d' * 32}/{key}"} for key in paths]
    job = {"id": "d" * 32, "arguments": {"scenario_id": "scenario"}, "status": "completed", "created_at": api.now(),
           "artifacts": artifacts, "artifact_paths": {key: str(path.relative_to(api.ROOT)) for key, path in paths.items()},
           "result": {"data": {"run_root": str(current)}, "artifacts": artifacts}}
    api.write_job(job)
    recovered = api.read_job(job["id"])
    assert [item["id"] for item in recovered["result"]["artifacts"]] == ["4", "16"]
    assert recovered["artifacts"][0]["url"].endswith("/4")
    assert old_file.is_file()
    assert "0" in json.loads(api.job_file(job["id"]).read_text(encoding="utf-8"))["artifact_paths"]
    with pytest.raises(ValueError, match="不存在"):
        api.bridge({"action": "artifact", "job_id": job["id"], "artifact_id": "0"})
    assert api.bridge({"action": "artifact", "job_id": job["id"], "artifact_id": "4"})["ok"]
