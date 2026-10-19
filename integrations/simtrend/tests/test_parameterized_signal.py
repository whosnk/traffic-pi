import xml.etree.ElementTree as ET

import pytest

from simtrend_app.parameterized_signal import (
    SignalPlanValidationError,
    parse_parameterized_signal_request,
    write_parameterized_signal_network,
)
from simtrend_app.agent.task_router import TaskRouter


def _write_network(path) -> None:
    path.write_text(
        """<net>
        <tlLogic id="j0" type="static" programID="0" offset="0">
            <phase duration="40" state="GGrr"/>
            <phase duration="3" state="yyrr"/>
            <phase duration="40" state="rrGG"/>
            <phase duration="3" state="rryy"/>
        </tlLogic>
        <tlLogic id="j1" type="static" programID="0" offset="0">
            <phase duration="30" state="G"/>
            <phase duration="3" state="y"/>
            <phase duration="3" state="r"/>
        </tlLogic>
        </net>""",
        encoding="utf-8",
    )


def test_parameterized_network_changes_only_selected_controller(tmp_path) -> None:
    source = tmp_path / "base.net.xml"
    target = tmp_path / "parameterized.net.xml"
    _write_network(source)

    plan = write_parameterized_signal_network(
        source,
        target,
        controller_id="j0",
        phase_durations=[50, 3, 30, 3],
    )

    root = ET.parse(target).getroot()
    j0 = root.find("tlLogic[@id='j0']")
    j1 = root.find("tlLogic[@id='j1']")
    assert [phase.get("duration") for phase in j0.findall("phase")] == ["50", "3", "30", "3"]
    assert [phase.get("duration") for phase in j1.findall("phase")] == ["30", "3", "3"]
    assert plan["original_cycle_seconds"] == 86
    assert plan["applied_cycle_seconds"] == 86
    assert plan["phases"][0]["phase_type"] == "green"
    assert plan["validation"]["ok"]


def test_parameterized_network_rejects_incomplete_phase_array(tmp_path) -> None:
    source = tmp_path / "base.net.xml"
    _write_network(source)

    with pytest.raises(SignalPlanValidationError) as exc_info:
        write_parameterized_signal_network(
            source,
            tmp_path / "target.net.xml",
            controller_id="j0",
            phase_durations=[50, 3],
        )

    assert exc_info.value.details["required_phase_count"] == 4
    assert exc_info.value.details["current_phase_durations"] == [40, 3, 40, 3]


def test_parameterized_network_rejects_unsafe_yellow_time(tmp_path) -> None:
    source = tmp_path / "base.net.xml"
    _write_network(source)

    with pytest.raises(SignalPlanValidationError, match="黄灯"):
        write_parameterized_signal_network(
            source,
            tmp_path / "target.net.xml",
            controller_id="j0",
            phase_durations=[50, 1, 30, 3],
        )


def test_parameterized_network_reports_available_controllers(tmp_path) -> None:
    source = tmp_path / "base.net.xml"
    _write_network(source)

    with pytest.raises(SignalPlanValidationError) as exc_info:
        write_parameterized_signal_network(
            source,
            tmp_path / "target.net.xml",
            controller_id="missing",
            phase_durations=[50, 3, 30, 3],
        )

    assert [item["controller_id"] for item in exc_info.value.details["available_controllers"]] == ["j0", "j1"]


def test_parse_parameterized_signal_request_and_route() -> None:
    text = "控制器 c00 的相位时长设为 50、3、34、3，运行600秒仿真，随机种子42"

    tool_input, missing = parse_parameterized_signal_request(text)
    route = TaskRouter().route(text)

    assert not missing
    assert tool_input == {
        "controller_id": "c00",
        "program_id": "0",
        "phase_durations": [50, 3, 34, 3],
        "duration_seconds": 600,
        "random_seed": 42,
        "render_animation": False,
        "result_slot": "latest",
    }
    assert route.task_type == "parameterized_signal_simulation"


def test_parse_parameterized_signal_request_selects_fixed_result_slots() -> None:
    reference, _ = parse_parameterized_signal_request(
        "控制器 c00 的相位时长设为 42、3、42、3，运行600秒仿真，保存为基准方案"
    )
    candidate, _ = parse_parameterized_signal_request(
        "控制器 c00 的相位时长设为 50、3、34、3，运行600秒仿真，保存为候选方案"
    )

    assert reference["result_slot"] == "reference"
    assert candidate["result_slot"] == "candidate"
