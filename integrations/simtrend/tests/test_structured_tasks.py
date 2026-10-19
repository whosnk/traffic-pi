from simtrend_app.agent.intent_parser import parse_intent
from simtrend_app.agent.task_router import TaskRouter
from simtrend_app.structured_tasks import (
    build_demand_adjustment_task,
    build_incident_task,
    demand_scope_options,
    demand_target_options,
)


def test_incident_task_generates_complete_routable_request() -> None:
    draft = build_incident_task(
        scenario_name="四交叉口路网",
        location_name="东北路口东进口直行车道",
        incident_type="追尾事故",
        incident_duration_minutes=10,
        lane_closure_count=1,
        objective="优先缓解排队",
        simulation_duration_seconds=600,
        spatial_selection={"edge_id": "e0_c10", "lane_id": "e0_c10_1"},
    )
    route = TaskRouter().route(draft.prompt)
    intent = parse_intent(draft.prompt, is_follow_up=False, task_route=route.as_dict())

    assert route.workflow == "signal_optimization"
    assert not intent.should_clarify
    assert intent.merged_intent["incident_duration_minutes"] == 10
    assert intent.merged_intent["lane_closure_count"] == 1
    assert intent.merged_intent["simulation_duration_seconds"] == 600


def test_incident_task_requires_precise_map_selection() -> None:
    try:
        build_incident_task(
            scenario_name="四交叉口路网",
            location_name="",
            incident_type="追尾事故",
            incident_duration_minutes=10,
            lane_closure_count=1,
            objective="优先缓解排队",
            simulation_duration_seconds=600,
            spatial_selection={},
        )
    except ValueError as exc:
        assert "地图" in str(exc)
    else:
        raise AssertionError("缺少地图选择时应拒绝生成事件任务")


def test_nanjing_demand_task_generates_demand_evaluation_request() -> None:
    draft = build_demand_adjustment_task(
        scenario_name="南京南站网约车停车管理",
        target="网约车到站流量",
        direction="提高",
        percentage=30,
        spatial_scope="南京南站北广场",
        simulation_duration_seconds=600,
    )
    route = TaskRouter().route(draft.prompt)
    intent = parse_intent(draft.prompt, is_follow_up=False, task_route=route.as_dict())

    assert route.workflow == "demand_impact_evaluation"
    assert not intent.should_clarify
    assert intent.merged_intent["demand_target"] == "ride_hailing_in"
    assert intent.merged_intent["demand_multiplier"] == 1.3
    assert intent.merged_intent["demand_spatial_scope"] == "north_plaza"


def test_demand_options_are_scenario_specific() -> None:
    assert demand_target_options("four_intersections") == ("全部流量",)
    assert "网约车到站流量" in demand_target_options("nanjing_south_ride_hailing")
    assert demand_scope_options("four_intersections") == ("整个场景",)
