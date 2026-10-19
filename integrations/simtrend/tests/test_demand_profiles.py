import xml.etree.ElementTree as ET
import json
from pathlib import Path

from simtrend_app.agent.intent_parser import build_structured_prompt, parse_intent
from simtrend_app.agent.task_router import TaskRouter
from simtrend_app.scenarios import load_scenarios
from simtrend_app.tool_scripts.common import (
    apply_demand_profile_to_routes,
    collect_metrics,
    infer_demand_profile,
    resolve_demand_profile,
)
from simtrend_app.tool_scripts.build_demand_plan import build_demand_plan


FOUR_INTERSECTIONS = Path("simtrend_scenarios/four_intersections")
NANJING_SOUTH = Path("simtrend_scenarios/nanjing_south_ride_hailing")


def test_light_scenario_is_hidden_from_default_selector(tmp_path) -> None:
    for scenario_id, hidden in [("four_intersections", False), ("four_intersections_light", True)]:
        folder = tmp_path / scenario_id
        folder.mkdir()
        (folder / "scenario.json").write_text(json.dumps({"id": scenario_id, "hidden": hidden}), encoding="utf-8")
    visible_ids = [scenario.id for scenario in load_scenarios(tmp_path)]
    all_ids = [scenario.id for scenario in load_scenarios(tmp_path, include_hidden=True)]

    assert "four_intersections" in visible_ids
    assert "four_intersections_light" not in visible_ids
    assert "four_intersections_light" in all_ids


def test_four_intersections_has_demand_profiles() -> None:
    scenario = next(item for item in load_scenarios() if item.id == "four_intersections")

    assert scenario.demand_profiles["light"]["multiplier"] == 0.61
    assert scenario.demand_profiles["standard"]["multiplier"] == 1.0


def test_parse_intent_extracts_light_demand_profile() -> None:
    result = parse_intent(
        "把四交叉口交通需求调成轻流量，东北路口东进口发生追尾事故，持续10分钟，封闭1条车道",
        is_follow_up=False,
    )

    assert result.merged_intent["demand_profile"] == "light"
    assert result.merged_intent["demand_profile_label"] == "轻流量"


def test_demand_adjustment_does_not_require_incident_fields() -> None:
    prompt = "把南京南站网约车到站流量提高30%，运行仿真并进行对比"
    route = TaskRouter().route(prompt)

    result = parse_intent(
        prompt,
        is_follow_up=False,
        task_route=route.as_dict(),
    )

    assert not result.should_clarify
    assert result.merged_intent["task_type"] == "demand_adjustment"
    assert result.merged_intent["demand_target"] == "ride_hailing_in"
    assert result.merged_intent["demand_multiplier"] == 1.3


def test_custom_nanjing_arrival_adjustment_only_changes_arrival_vehicles() -> None:
    prompt = "把南京南站网约车到站流量提高30%，运行仿真并进行对比"
    route = TaskRouter().route(prompt)
    result = parse_intent(prompt, is_follow_up=False, task_route=route.as_dict())
    profile = infer_demand_profile(build_structured_prompt(prompt, result))
    route_file = NANJING_SOUTH / "routes" / "intersection.rou.xml"
    root = ET.parse(route_file).getroot()

    adjustment = apply_demand_profile_to_routes(root, profile)
    group_counts = {group["group_key"]: group for group in adjustment["vehicle_group_summaries"]}

    assert profile["target"] == "ride_hailing_in"
    assert profile["target_multiplier"] == 1.3
    assert group_counts["ride_hailing_in"]["adjusted_count"] == round(507 * 1.3)
    assert group_counts["ride_hailing_out"]["adjusted_count"] == 256
    assert group_counts["background"]["adjusted_count"] == 253


def test_demand_impact_plan_keeps_reference_and_adjusted_profiles_separate() -> None:
    prompt = "把南京南站网约车到站流量提高30%，运行仿真并进行对比"
    route = TaskRouter().route(prompt)
    intent = parse_intent(prompt, is_follow_up=False, task_route=route.as_dict())

    plan = build_demand_plan(build_structured_prompt(prompt, intent), 600)

    assert plan["workflow_type"] == "demand_impact_evaluation"
    assert plan["duration_seconds"] == 600
    assert plan["target"] == "ride_hailing_in"
    assert plan["reference_profile"]["multiplier"] == 1.0
    assert plan["adjusted_profile"]["target_multiplier"] == 1.3


def test_demand_impact_extracts_time_window_and_north_plaza_scope() -> None:
    prompt = "仿真第300到900秒，将南京南站北广场网约车到站流量提高30%，与原始需求进行对比"
    route = TaskRouter().route(prompt)
    intent = parse_intent(prompt, is_follow_up=False, task_route=route.as_dict())

    assert not intent.should_clarify
    assert intent.merged_intent["task_type"] == "demand_adjustment"
    assert intent.merged_intent["simulation_duration_seconds"] == 900
    assert intent.merged_intent["demand_window_start_s"] == 300
    assert intent.merged_intent["demand_window_end_s"] == 900
    assert intent.merged_intent["demand_spatial_scope"] == "north_plaza"

    plan = build_demand_plan(
        build_structured_prompt(prompt, intent),
        intent.merged_intent["simulation_duration_seconds"],
        NANJING_SOUTH,
    )

    assert plan["adjustment_scope"]["time_window_start_s"] == 300
    assert plan["adjustment_scope"]["time_window_end_s"] == 900
    assert plan["adjustment_scope"]["spatial_scope_label"] == "南京南站北广场区域"
    assert plan["adjustment_scope"]["spatial_match_mode"] == "destination"
    assert "189391594#0" in plan["adjustment_scope"]["spatial_edge_ids"]


def test_nanjing_time_and_space_scoped_arrival_adjustment() -> None:
    prompt = "仿真第300到900秒，将南京南站北广场网约车到站流量提高30%，与原始需求进行对比"
    route = TaskRouter().route(prompt)
    intent = parse_intent(prompt, is_follow_up=False, task_route=route.as_dict())
    plan = build_demand_plan(build_structured_prompt(prompt, intent), 900, NANJING_SOUTH)
    root = ET.parse(NANJING_SOUTH / "routes" / "intersection.rou.xml").getroot()

    adjustment = apply_demand_profile_to_routes(root, plan["adjusted_profile"])
    groups = {group["group_key"]: group for group in adjustment["vehicle_group_summaries"]}
    clones = [
        vehicle
        for vehicle in root.findall("vehicle")
        if "__demand_" in vehicle.get("id", "")
    ]
    spatial_edges = set(plan["adjustment_scope"]["spatial_edge_ids"])
    route_edges = {
        route.get("id"): (route.get("edges") or "").split()
        for route in root.findall("route")
    }

    assert groups["ride_hailing_in"]["eligible_count"] == 20
    assert groups["ride_hailing_in"]["adjusted_eligible_count"] == 26
    assert groups["ride_hailing_in"]["adjusted_count"] == 513
    assert groups["ride_hailing_out"]["adjusted_count"] == 256
    assert groups["background"]["adjusted_count"] == 253
    assert adjustment["adjusted_vehicle_count"] == 1022
    assert len(clones) == 6
    assert all(300 <= float(vehicle.get("depart", "0")) < 900 for vehicle in clones)
    clone_routes = [
        (vehicle.find("route").get("edges") or "").split()
        if vehicle.find("route") is not None
        else route_edges[vehicle.get("route")]
        for vehicle in clones
    ]
    assert all(edges[-1] in spatial_edges for edges in clone_routes)


def test_time_window_splits_continuous_flows_without_scaling_outside_window() -> None:
    root = ET.fromstring(
        '<routes><route id="r" edges="a b"/>'
        '<flow id="f" route="r" begin="0" end="1200" vehsPerHour="100"/></routes>'
    )
    profile = {
        "key": "custom",
        "label": "全流量 1.30 倍",
        "multiplier": 1.3,
        "time_window_start_s": 300,
        "time_window_end_s": 900,
    }

    adjustment = apply_demand_profile_to_routes(root, profile)

    assert adjustment["scaled_flow_ids"] == ["f"]
    assert adjustment["adjusted_total_vehs_per_hour"] == 115.0
    assert root.find("flow[@id='f__before']").get("vehsPerHour") == "100"
    assert root.find("flow[@id='f__adjusted']").get("vehsPerHour") == "130"
    assert root.find("flow[@id='f__after']").get("vehsPerHour") == "100"


def test_collect_metrics_reads_cumulative_arrivals_from_final_step(tmp_path) -> None:
    statistics = tmp_path / "statistics.xml"
    summary = tmp_path / "summary.xml"
    tripinfo = tmp_path / "tripinfo.xml"
    queue = tmp_path / "queue.xml"
    statistics.write_text(
        '<statistics><vehicles inserted="3" running="0"/>'
        '<vehicleTripStatistics waitingTime="2" timeLoss="3" count="3"/></statistics>',
        encoding="utf-8",
    )
    summary.write_text(
        '<summary><step time="0" arrived="0" halting="1"/>'
        '<step time="1" arrived="2" halting="0"/>'
        '<step time="2" arrived="3" halting="0"/></summary>',
        encoding="utf-8",
    )
    tripinfo.write_text("<tripinfos/>", encoding="utf-8")
    queue.write_text("<queue-export/>", encoding="utf-8")

    metrics = collect_metrics(
        {
            "statistics": str(statistics),
            "summary": str(summary),
            "tripinfo": str(tripinfo),
            "queue": str(queue),
        },
        {"lane_ids": [], "route_prefixes": ["rh_in_"]},
    )

    assert metrics["arrived_vehicle_count"] == 3


def test_demand_profile_scales_four_intersection_flows() -> None:
    route_file = FOUR_INTERSECTIONS / "routes" / "intersection.rou.xml"
    root = ET.parse(route_file).getroot()
    profile = resolve_demand_profile(FOUR_INTERSECTIONS, infer_demand_profile("轻流量"))

    adjustment = apply_demand_profile_to_routes(root, profile)

    assert adjustment["enabled"]
    assert adjustment["profile_key"] == "light"
    assert adjustment["scaled_flow_count"] == 24
    assert adjustment["original_total_vehs_per_hour"] == 6480
    assert round(adjustment["adjusted_total_vehs_per_hour"], 1) == 3952.8
    assert root.find("flow[@id='flow_e0_through']").get("vehsPerHour") == "317.2"


def test_nanjing_heavy_profile_clones_explicit_vehicles() -> None:
    route_file = NANJING_SOUTH / "routes" / "intersection.rou.xml"
    root = ET.parse(route_file).getroot()
    profile = resolve_demand_profile(NANJING_SOUTH, infer_demand_profile("高流量"))

    adjustment = apply_demand_profile_to_routes(root, profile)

    assert adjustment["enabled"]
    assert adjustment["vehicle_demand_enabled"]
    original_vehicle_count = 1016
    original_rh_in_count = 507
    original_background_count = 253
    assert adjustment["original_vehicle_count"] == original_vehicle_count
    assert adjustment["adjusted_vehicle_count"] > original_vehicle_count
    assert adjustment["cloned_vehicle_count"] > 0
    assert any(
        vehicle.get("id", "").startswith("rh_in_") and "__demand_" in vehicle.get("id", "")
        for vehicle in root.findall("vehicle")
    )
    group_counts = {group["group_key"]: group for group in adjustment["vehicle_group_summaries"]}
    assert group_counts["ride_hailing_in"]["adjusted_count"] == round(original_rh_in_count * 1.35)
    assert group_counts["background"]["adjusted_count"] == round(original_background_count * 1.1)


def test_nanjing_light_profile_removes_explicit_vehicles() -> None:
    route_file = NANJING_SOUTH / "routes" / "intersection.rou.xml"
    root = ET.parse(route_file).getroot()
    profile = resolve_demand_profile(NANJING_SOUTH, infer_demand_profile("轻流量"))

    adjustment = apply_demand_profile_to_routes(root, profile)

    assert adjustment["enabled"]
    assert adjustment["vehicle_demand_enabled"]
    original_vehicle_count = 1016
    assert adjustment["original_vehicle_count"] == original_vehicle_count
    assert adjustment["adjusted_vehicle_count"] < original_vehicle_count
    assert adjustment["removed_vehicle_count"] > 0
    assert not any("__demand_" in vehicle.get("id", "") for vehicle in root.findall("vehicle"))
