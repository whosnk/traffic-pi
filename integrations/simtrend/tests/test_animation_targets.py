from simtrend_app.agent.workflow import AgentWorkflow
from simtrend_app.animation_targets import (
    comparison_animation_targets,
    merge_animation_targets,
    ordered_animation_targets,
    parameterized_animation_targets,
    replay_charts,
)
from simtrend_app.tools.base import ToolResult


def test_parameterized_target_keeps_cfg_without_gif() -> None:
    targets = parameterized_animation_targets(
        {
            "signal_plan": {"result_slot": "reference"},
            "cfg_file": "reference.sumocfg",
            "animation": {},
        }
    )

    target = targets["parameterized_reference"]
    assert target["label"] == "参数化基准方案动画"
    assert target["cfg_file"] == "reference.sumocfg"
    assert "gif_file" not in target


def test_parameterized_target_includes_successful_gif() -> None:
    targets = parameterized_animation_targets(
        {
            "signal_plan": {"result_slot": "candidate"},
            "cfg_file": "candidate.sumocfg",
            "animation": {"ok": True, "gif_file": "candidate.gif", "frame_count": 60},
        }
    )

    target = targets["parameterized_candidate"]
    assert target["gif_file"] == "candidate.gif"
    assert target["replay_status"]["frame_count"] == 60


def test_merge_preserves_reference_when_candidate_arrives() -> None:
    reference = parameterized_animation_targets(
        {"signal_plan": {"result_slot": "reference"}, "cfg_file": "reference.sumocfg"}
    )
    candidate = parameterized_animation_targets(
        {"signal_plan": {"result_slot": "candidate"}, "cfg_file": "candidate.sumocfg"}
    )

    merged = merge_animation_targets(reference, candidate)

    assert set(merged) == {"parameterized_reference", "parameterized_candidate"}
    assert ordered_animation_targets(merged)[0][0] == "parameterized_candidate"


def test_comparison_restores_both_parameterized_animations() -> None:
    targets = comparison_animation_targets(
        {
            "reference": {
                "selector": "reference",
                "cfg_file": "reference.sumocfg",
                "animation": {"ok": True, "gif_file": "reference.gif"},
            },
            "candidate": {
                "selector": "candidate",
                "cfg_file": "candidate.sumocfg",
                "animation": {"ok": True, "gif_file": "candidate.gif"},
            },
        }
    )

    assert targets["parameterized_reference"]["gif_file"] == "reference.gif"
    assert targets["parameterized_candidate"]["gif_file"] == "candidate.gif"
    assert len(replay_charts(targets)) == 2


def test_workflow_parameterized_result_exposes_chat_chart_and_gui_target() -> None:
    tool_result = ToolResult(
        ok=True,
        message="ok",
        data={
            "signal_plan": {"result_slot": "candidate", "controller_id": "c00"},
            "cfg_file": "candidate.sumocfg",
            "animation": {"ok": True, "gif_file": "candidate.gif"},
            "diagnosis": {"summary": {"primary_bottleneck": "road_a"}},
        },
    )

    result = AgentWorkflow._build_parameterized_signal_result(
        "运行参数化仿真并生成动画",
        tool_result,
        {"result_slot": "candidate"},
    )

    assert result.animation_targets["parameterized_candidate"]["cfg_file"] == "candidate.sumocfg"
    assert result.charts[0]["type"] == "replay_gif"
    assert result.charts[0]["gif_file"] == "candidate.gif"
