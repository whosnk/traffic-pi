from pathlib import Path

from simtrend_app.scenario_runtime import ScenarioRuntime


SCENARIO_PATH = Path("simtrend_scenarios/nanjing_south_ride_hailing")


def test_scenario_runtime_loads_metadata_and_paths() -> None:
    runtime = ScenarioRuntime.from_project_dir(SCENARIO_PATH)

    assert runtime.scenario_id == "nanjing_south_ride_hailing"
    assert runtime.name == "南京南站网约车停车管理"
    assert runtime.project_dir == SCENARIO_PATH.resolve()
    assert runtime.net_file.name == "intersection.net.xml"
    assert runtime.route_file.name == "intersection.rou.xml"
    assert runtime.agent_runs_dir == runtime.outputs_dir / "agent_runs"
    assert runtime.map_enabled
    assert runtime.has_capability("上客区")


def test_scenario_runtime_validates_required_files() -> None:
    runtime = ScenarioRuntime.from_project_dir(SCENARIO_PATH)

    runtime.validate_required_files()


def test_scenario_runtime_creates_run_directories(tmp_path) -> None:
    runtime = ScenarioRuntime.from_payload(
        {"id": "tmp_scene", "name": "临时场景"},
        tmp_path,
    )

    run_root = runtime.create_run_root(reuse_latest=True)
    run_dirs = runtime.run_subdirs(run_root)
    output_paths = runtime.output_paths(run_dirs["baseline"])

    assert run_root == tmp_path / "outputs" / "agent_runs" / "latest_run"
    assert set(run_dirs) == {"json", "baseline", "optimized"}
    assert output_paths["tripinfo"].name == "tripinfo.xml"
    assert output_paths["fcd"].name == "fcd.xml"
