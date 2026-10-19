import json
from pathlib import Path

from simtrend_app.agent.task_router import TaskRouter
from simtrend_app.config import Settings
from simtrend_app.fair_simulation_comparison import compare_simulation_runs


def _settings(project: Path) -> Settings:
    return Settings("", "", "", str(project), False, False, False, 1800)


def _network_text(first_green: int, second_green: int, state: str = "Gr") -> str:
    return f"""<net>
    <edge id="road_a" name="测试进口"><lane id="road_a_0" index="0"/></edge>
    <edge id="road_b" name="测试出口"><lane id="road_b_0" index="0"/></edge>
    <tlLogic id="j0" type="static" programID="0">
        <phase duration="{first_green}" state="{state}"/>
        <phase duration="3" state="yr"/>
        <phase duration="{second_green}" state="rG"/>
        <phase duration="3" state="ry"/>
    </tlLogic>
    <connection from="road_a" to="road_b" fromLane="0" toLane="0" tl="j0" linkIndex="0"/>
    </net>"""


def _write_run(
    project: Path,
    slot: str,
    *,
    seed: int,
    green_times: tuple[int, int],
    avg_wait: float,
    time_loss: float,
    arrived: int,
    halting: int,
    edge_speed: float,
    edge_wait: float,
    edge_loss: float,
    state: str = "Gr",
) -> None:
    run_root = project / "outputs" / "agent_runs" / f"parameterized_{slot}"
    json_dir = run_root / "json"
    simulation_dir = run_root / "simulation"
    json_dir.mkdir(parents=True)
    simulation_dir.mkdir(parents=True)
    net_file = simulation_dir / "parameterized_intersection.net.xml"
    net_file.write_text(_network_text(*green_times, state=state), encoding="utf-8")
    route_file = simulation_dir / "runtime_routes.rou.xml"
    route_file.write_text(
        '<routes><route id="r0" edges="road_a road_b"/>'
        '<vehicle id="v0" route="r0" depart="0"/></routes>',
        encoding="utf-8",
    )
    statistics = simulation_dir / "statistics.xml"
    statistics.write_text(
        f'<statistics><vehicles inserted="10" running="1"/>'
        f'<vehicleTripStatistics waitingTime="{avg_wait}" timeLoss="{time_loss}" count="9"/></statistics>',
        encoding="utf-8",
    )
    summary = simulation_dir / "summary.xml"
    summary.write_text(
        f'<summary><step time="0" arrived="0" halting="0"/>'
        f'<step time="600" arrived="{arrived}" halting="{halting}"/></summary>',
        encoding="utf-8",
    )
    tripinfo = simulation_dir / "tripinfo.xml"
    tripinfo.write_text("<tripinfos/>", encoding="utf-8")
    queue = simulation_dir / "queue.xml"
    queue.write_text("<queue-export/>", encoding="utf-8")
    edge_metrics = simulation_dir / "edge_metrics.xml"
    edge_metrics.write_text(
        f'<meandata><interval begin="0" end="600">'
        f'<edge id="road_a" sampledSeconds="100" entered="10" left="9" '
        f'speed="{edge_speed}" density="5" waitingTime="{edge_wait}" timeLoss="{edge_loss}"/>'
        f'</interval></meandata>',
        encoding="utf-8",
    )
    payload = {
        "workflow_type": "parameterized_signal_simulation",
        "variant": "parameterized",
        "result_slot": slot,
        "duration_seconds": 600,
        "random_seed": seed,
        "scenario_runtime": {"scenario_id": "fair_test"},
        "net_file": str(net_file),
        "route_files": [str(route_file)],
        "edge_metrics_file": str(edge_metrics),
        "outputs": {
            "statistics": str(statistics),
            "summary": str(summary),
            "tripinfo": str(tripinfo),
            "queue": str(queue),
        },
        "run": {"ok": True, "returncode": 0},
    }
    (json_dir / "parameterized_result.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _project(tmp_path: Path, candidate_seed: int = 42, candidate_state: str = "Gr") -> Path:
    network_dir = tmp_path / "network"
    network_dir.mkdir(parents=True)
    (tmp_path / "scenario.json").write_text(
        json.dumps({"id": "fair_test", "name": "公平对比测试"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (network_dir / "intersection.net.xml").write_text(_network_text(42, 42), encoding="utf-8")
    _write_run(
        tmp_path,
        "reference",
        seed=42,
        green_times=(42, 42),
        avg_wait=20,
        time_loss=30,
        arrived=8,
        halting=5,
        edge_speed=5,
        edge_wait=60,
        edge_loss=70,
    )
    _write_run(
        tmp_path,
        "candidate",
        seed=candidate_seed,
        green_times=(50, 34),
        avg_wait=10,
        time_loss=15,
        arrived=9,
        halting=3,
        edge_speed=10,
        edge_wait=20,
        edge_loss=25,
        state=candidate_state,
    )
    return tmp_path


def test_fair_comparison_accepts_only_signal_duration_change(tmp_path) -> None:
    project = _project(tmp_path)

    result = compare_simulation_runs(_settings(project), "reference", "candidate", top_n=3)

    assert result.ok
    comparison = result.data["comparison"]
    assert comparison["comparability"]["strictly_comparable"]
    assert comparison["comparability"]["failed_count"] == 0
    assert comparison["metric_changes"]["overall_avg_wait_s"]["delta"] == -10
    assert comparison["signal_changes"][0]["controller_id"] == "j0"
    assert comparison["top_improved_edges"][0]["edge_id"] == "road_a"
    assert comparison["conclusion"]["verdict"] == "候选方案在本次实验中表现更好"
    assert result.data["spatial_selection"]["edge_id"] == "road_a"


def test_seed_mismatch_blocks_causal_conclusion(tmp_path) -> None:
    project = _project(tmp_path, candidate_seed=43)

    result = compare_simulation_runs(_settings(project), "reference", "candidate")

    assert result.ok
    comparison = result.data["comparison"]
    assert not comparison["comparability"]["strictly_comparable"]
    seed_check = next(item for item in comparison["comparability"]["checks"] if item["name"] == "随机种子")
    assert seed_check["status"] == "fail"
    assert comparison["conclusion"]["verdict"] == "不可严格比较"
    assert comparison["conclusion"]["evidence_level"] == "描述性观察"


def test_signal_state_change_blocks_fair_comparison(tmp_path) -> None:
    project = _project(tmp_path, candidate_state="rr")

    result = compare_simulation_runs(_settings(project), "reference", "candidate")

    topology_check = next(
        item for item in result.data["comparison"]["comparability"]["checks"]
        if item["name"] == "路网拓扑与相位放行关系"
    )
    assert topology_check["status"] == "fail"


def test_fair_comparison_router_uses_fixed_slots() -> None:
    route = TaskRouter().route("请公平对比基准方案和候选方案，判断是否改善")

    assert route.task_type == "fair_simulation_comparison"
    assert route.workflow == "fair_simulation_comparison"


def test_missing_candidate_slot_returns_recoverable_error(tmp_path) -> None:
    project = _project(tmp_path)
    candidate = project / "outputs/agent_runs/parameterized_candidate/json/parameterized_result.json"
    candidate.unlink()

    result = compare_simulation_runs(_settings(project), "reference", "candidate")

    assert not result.ok
    assert result.data["error"]["code"] == "COMPARISON_INPUT_INVALID"
    assert result.data["error"]["recoverable"]
