import json
from pathlib import Path

from simtrend_app.agent.task_router import TaskRouter
from simtrend_app.config import Settings
from simtrend_app.signal_control_query import build_signal_control_index, query_signal_control
from simtrend_app.scenario_runtime import ScenarioRuntime


def _project(tmp_path: Path) -> Path:
    network_dir = tmp_path / "network"
    network_dir.mkdir(parents=True)
    (tmp_path / "scenario.json").write_text(
        json.dumps(
            {
                "id": "signal_test",
                "name": "信号查询测试",
                "intersections": [{"id": "j0", "name": "测试路口"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (network_dir / "intersection.net.xml").write_text(
        """<net>
        <edge id="west_in" name="西进口"><lane id="west_in_0"/></edge>
        <edge id="east_out" name="东出口"><lane id="east_out_0"/></edge>
        <edge id="north_out" name="北出口"><lane id="north_out_0"/></edge>
        <tlLogic id="j0" type="static" programID="0" offset="0">
            <phase duration="30" state="Gr"/>
            <phase duration="3" state="yr"/>
            <phase duration="20" state="rG"/>
            <phase duration="3" state="ry"/>
        </tlLogic>
        <connection from="west_in" to="east_out" fromLane="0" toLane="0" tl="j0" linkIndex="0"/>
        <connection from="west_in" to="north_out" fromLane="0" toLane="0" tl="j0" linkIndex="1"/>
        </net>""",
        encoding="utf-8",
    )
    return tmp_path


def _settings(project: Path) -> Settings:
    return Settings("", "", "", str(project), False, False, False, 1800)


def test_signal_index_maps_phase_state_to_controlled_connections(tmp_path) -> None:
    project = _project(tmp_path)

    index = build_signal_control_index(ScenarioRuntime.from_project_dir(project))
    controller = index["controllers"][("j0", "0")]

    assert controller["display_name"] == "测试路口"
    assert controller["cycle_seconds"] == 56
    assert controller["phase_durations_s"] == [30, 3, 20, 3]
    assert controller["phases"][0]["active_connections"][0]["to_edge_id"] == "east_out"
    assert controller["phases"][2]["active_connections"][0]["to_edge_id"] == "north_out"


def test_query_by_edge_returns_controller_template_and_map_selection(tmp_path) -> None:
    project = _project(tmp_path)

    result = query_signal_control(_settings(project), query="查询道路 west_in 由哪个信号控制器管理")

    assert result.ok
    assert result.data["query_status"] == "matched"
    assert result.data["signal_context"]["controller_id"] == "j0"
    assert result.data["spatial_selection"]["edge_id"] == "west_in"
    assert "相位时长设为 30、3、20、3" in result.message
    assert "west_in → east_out" in result.message


def test_query_by_lane_and_controller_use_same_signal_context(tmp_path) -> None:
    project = _project(tmp_path)

    lane_result = query_signal_control(_settings(project), lane_id="west_in_0")
    controller_result = query_signal_control(_settings(project), controller_id="j0")

    assert lane_result.ok and controller_result.ok
    assert lane_result.data["signal_context"]["controller_id"] == "j0"
    assert controller_result.data["signal_context"]["phase_count"] == 4


def test_known_uncontrolled_road_returns_explicit_read_only_conclusion(tmp_path) -> None:
    project = _project(tmp_path)

    result = query_signal_control(
        _settings(project),
        query="查询道路 east_out 由哪个信号控制器管理",
    )

    assert result.ok
    assert result.data["query_status"] == "uncontrolled"
    assert "未由信号控制器直接管理" in result.message
    assert "没有可查询的信号相位方案" in result.message


def test_list_signal_controllers_and_route_query(tmp_path) -> None:
    project = _project(tmp_path)

    result = query_signal_control(_settings(project), query="当前场景有哪些信号控制器？")
    route = TaskRouter().route("查询道路 west_in 由哪个信号控制器管理，并显示当前相位配置")

    assert result.ok
    assert result.data["query_status"] == "list"
    assert "共识别到 **1** 个信号控制程序" in result.message
    assert route.task_type == "signal_control_query"
    assert route.workflow == "signal_control_query"


def test_signal_query_does_not_capture_parameterized_simulation() -> None:
    route = TaskRouter().route("控制器 c00 的相位时长设为 50、3、34、3，运行600秒仿真")

    assert route.task_type == "parameterized_signal_simulation"


def test_edge_id_containing_controller_id_keeps_edge_as_query_target(tmp_path) -> None:
    project = _project(tmp_path)
    network_file = project / "network/intersection.net.xml"
    text = network_file.read_text(encoding="utf-8").replace("west_in", "west_j0")
    network_file.write_text(text, encoding="utf-8")

    result = query_signal_control(
        _settings(project),
        query="查询道路 west_j0 由哪个信号控制器管理，并显示当前相位配置",
    )

    assert result.ok
    assert result.data["signal_context"]["controller_id"] == "j0"
    assert result.data["spatial_selection"]["edge_id"] == "west_j0"
