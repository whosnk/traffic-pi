from pathlib import Path

from simtrend_app.map_selector import (
    _complete_selection,
    build_generic_spatial_objects,
    build_spatial_context,
    build_topology_selection,
    load_map_objects,
)
from simtrend_app.agent.intent_parser import parse_intent
from simtrend_app.scenarios import load_scenarios
from simtrend_app.tool_scripts.common import (
    apply_pickup_stops_to_routes,
    infer_target_plan,
    load_pickup_zones,
    write_incident_overlay_route,
    write_pickup_zone_additional,
    write_safe_runtime_routes,
)

import xml.etree.ElementTree as ET


SCENARIO_PATH = Path("simtrend_scenarios/nanjing_south_ride_hailing")
FOUR_INTERSECTIONS_PATH = Path("simtrend_scenarios/four_intersections")
MAP_CONFIG = {
    "geo_edge_file": "raw/plain.edg.xml",
    "net_file": "network/intersection.net.xml",
}


def test_nanjing_map_objects_match_real_network_lanes() -> None:
    scenario = next(item for item in load_scenarios() if item.id == "nanjing_south_ride_hailing")
    edges, lanes_by_edge = load_map_objects(scenario.path, scenario.map_config)

    assert any(edge["edge_id"] == "189391594#0" for edge in edges)
    assert any(edge["edge_id"] == "760767137#1" for edge in edges)
    assert lanes_by_edge["189391594#0"][0]["lane_id"] == "189391594#0_0"


def test_nanjing_map_filter_hides_dead_ends_and_minor_paths() -> None:
    scenario = next(item for item in load_scenarios() if item.id == "nanjing_south_ride_hailing")

    filtered_edges, _ = load_map_objects(scenario.path, scenario.map_config)
    unfiltered_config = {
        key: value
        for key, value in scenario.map_config.items()
        if key != "display_filter"
    }
    unfiltered_edges, _ = load_map_objects(scenario.path, unfiltered_config)

    filtered_ids = {edge["edge_id"] for edge in filtered_edges}
    assert len(filtered_edges) < len(unfiltered_edges)
    assert "189391585#1" not in filtered_ids
    assert not any(edge["road_type"] == "highway.footway" for edge in filtered_edges)
    assert {"189391594#0", "760767137#1"}.issubset(filtered_ids)


def test_four_intersections_can_load_clickable_map_objects() -> None:
    scenario = next(item for item in load_scenarios() if item.id == "four_intersections")

    edges, lanes_by_edge = load_map_objects(scenario.path, scenario.map_config)
    east_edge = next(edge for edge in edges if edge["edge_id"] == "e0_c10")

    assert len(edges) == 24
    assert east_edge["edge_name"] == "东北路口东进口"
    assert len(east_edge["coordinates"]) == 2
    assert lanes_by_edge["e0_c10"][1]["lane_id"] == "e0_c10_1"


def test_map_road_click_defaults_four_intersection_approach_to_through_lane() -> None:
    scenario = next(item for item in load_scenarios() if item.id == "four_intersections")
    edges, lanes_by_edge = load_map_objects(scenario.path, scenario.map_config)
    edge = next(item for item in edges if item["edge_id"] == "e0_c10")

    selection = _complete_selection(
        {
            **edge,
            "selector_key": "edge:e0_c10",
            "object_type": "road",
            "display_name": edge["edge_name"],
        },
        lanes_by_edge,
        scenario,
    )

    assert selection["lane_id"] == "e0_c10_1"
    assert selection["movement_key"] == "through"
    assert selection["movement_label"] == "直行"
    assert selection["display_name"] == "东北路口东进口直行车道"


def test_map_outbound_road_uses_lane_number_without_false_turn_label() -> None:
    scenario = next(item for item in load_scenarios() if item.id == "four_intersections")
    edges, lanes_by_edge = load_map_objects(scenario.path, scenario.map_config)
    edge = next(item for item in edges if item["edge_id"] == "c00_w0")

    selection = _complete_selection(
        {
            **edge,
            "selector_key": "edge:c00_w0",
            "object_type": "road",
            "display_name": edge["edge_name"],
        },
        lanes_by_edge,
        scenario,
    )

    assert selection["lane_id"] == "c00_w0_0"
    assert selection["movement_key"] is None
    assert selection["movement_label"] == "车道 1"
    assert selection["display_name"].endswith("·车道 1")


def test_map_selection_overrides_generic_nanjing_target() -> None:
    selection = {
        "object_type": "pickup_zone",
        "display_name": "南京南站北广场网约车上客区",
        "edge_id": "189391594#0",
        "lane_id": "189391594#0_0",
        "lane_ids": ["189391594#0_0"],
    }
    prompt = "上客区排队严重，请进行优化。\n\n" + build_spatial_context(selection)

    plan = infer_target_plan(prompt, "nanjing_south_ride_hailing")

    assert plan["target_label"] == "南京南站北广场网约车上客区"
    assert plan["selected_edge_id"] == "189391594#0"
    assert plan["blocked_lane_id"] == "189391594#0_0"
    assert plan["lane_ids"] == ["189391594#0_0"]


def test_generic_spatial_objects_cover_four_intersection_approaches() -> None:
    scenario = next(item for item in load_scenarios() if item.id == "four_intersections")

    objects = build_generic_spatial_objects(scenario)
    target = next(
        item
        for item in objects
        if item["intersection_id"] == "c10" and item["approach_key"] == "east"
    )

    assert len(objects) == 16
    assert target["intersection_name"] == "东北路口"
    assert target["approach_label"] == "东进口"
    assert target["edge_id"] == "e0_c10"
    assert [lane["lane_id"] for lane in target["lanes"]] == ["e0_c10_0", "e0_c10_1", "e0_c10_2"]
    assert [lane["movement_label"] for lane in target["lanes"]] == ["左转", "直行", "右转"]


def test_topology_selection_defaults_to_through_lane() -> None:
    scenario = next(item for item in load_scenarios() if item.id == "four_intersections")
    objects = build_generic_spatial_objects(scenario)
    target = next(
        item
        for item in objects
        if item["intersection_id"] == "c10" and item["approach_key"] == "east"
    )

    selection = build_topology_selection(scenario.id, target)

    assert selection["object_type"] == "intersection_lane"
    assert selection["display_name"] == "东北路口东进口直行车道"
    assert selection["edge_id"] == "e0_c10"
    assert selection["lane_id"] == "e0_c10_1"
    assert selection["lane_ids"] == ["e0_c10_0", "e0_c10_1", "e0_c10_2"]


def test_generic_spatial_selection_overrides_four_intersection_target() -> None:
    selection = {
        "scenario_id": "four_intersections",
        "object_type": "intersection_lane",
        "display_name": "东北路口东进口直行车道",
        "edge_id": "e0_c10",
        "lane_id": "e0_c10_1",
        "lane_ids": ["e0_c10_0", "e0_c10_1", "e0_c10_2"],
    }
    prompt = "这里发生追尾事故，持续10分钟，封闭1条车道。\n\n" + build_spatial_context(selection)

    plan = infer_target_plan(prompt, "four_intersections")

    assert plan["target_label"] == "东北路口东进口直行车道"
    assert plan["selected_edge_id"] == "e0_c10"
    assert plan["blocked_lane_id"] == "e0_c10_1"
    assert plan["lane_ids"] == ["e0_c10_1"]


def test_map_selection_satisfies_location_clarification() -> None:
    selection = {
        "object_type": "road",
        "display_name": "道路 189391594#0",
        "edge_id": "189391594#0",
        "lane_id": "189391594#0_0",
        "lane_ids": ["189391594#0_0"],
    }
    prompt = "这里发生追尾事故，持续10分钟，封闭1条车道。\n\n" + build_spatial_context(selection)

    result = parse_intent(prompt, is_follow_up=False)

    assert result.merged_intent["location_text"] == "道路 189391594#0"
    assert "事故位置/受影响进口" not in result.missing_fields
    assert not result.should_clarify


def test_full_lane_closure_removes_inline_vehicle_routes(tmp_path) -> None:
    route_file = SCENARIO_PATH / "routes" / "intersection.rou.xml"
    net_file = SCENARIO_PATH / "network" / "intersection.net.xml"
    runtime_file = tmp_path / "runtime_routes.rou.xml"
    incident_context = {
        "incident_duration_minutes": 10,
        "blocked_lane_id": "760767144_0",
        "closed_lane_ids": ["760767144_0"],
        "blocked_edge_id": "760767144",
    }

    result = write_safe_runtime_routes(
        route_file,
        net_file,
        runtime_file,
        incident_context,
        duration_seconds=600,
    )
    impact = result["incident_impact"]

    runtime_text = runtime_file.read_text(encoding="utf-8")
    assert len(impact["removed_vehicle_ids"]) > 0
    assert all(f'id="{vehicle_id}"' not in runtime_text for vehicle_id in impact["removed_vehicle_ids"][:10])


def test_closure_detects_routes_that_enter_a_closed_destination_lane(tmp_path) -> None:
    route_file = FOUR_INTERSECTIONS_PATH / "routes" / "intersection.rou.xml"
    net_file = FOUR_INTERSECTIONS_PATH / "network" / "intersection.net.xml"
    runtime_file = tmp_path / "runtime_routes.rou.xml"
    incident_context = {
        "incident_duration_minutes": 10,
        "blocked_lane_id": "c00_w0_0",
        "closed_lane_ids": ["c00_w0_0"],
        "blocked_edge_id": "c00_w0",
    }

    result = write_safe_runtime_routes(
        route_file,
        net_file,
        runtime_file,
        incident_context,
        duration_seconds=600,
    )
    impact = result["incident_impact"]
    runtime_root = ET.parse(runtime_file).getroot()
    remaining_flow_ids = {flow.get("id") for flow in runtime_root.findall("flow")}

    assert "n0_right" in impact["affected_route_ids"]
    assert "flow_n0_right" in impact["removed_flow_ids"]
    assert "flow_n0_right" not in remaining_flow_ids
    assert "e0_through" not in impact["affected_route_ids"]
    assert "flow_e0_through" in remaining_flow_ids


def test_incident_blocker_route_is_always_placed_on_blocked_edge(tmp_path) -> None:
    overlay_file = tmp_path / "incident_overlay.rou.xml"
    incident_context = {
        "incident_duration_minutes": 10,
        "route_id": "east_west",
        "route_edges": "e0_c10 c10_c00",
        "blocked_edge_id": "w0_c00",
        "blocked_lane_id": "w0_c00_1",
    }

    write_incident_overlay_route(overlay_file, incident_context, duration_seconds=600)

    overlay_root = ET.parse(overlay_file).getroot()
    route = overlay_root.find("route")
    vehicle = overlay_root.find("vehicle")
    stop = vehicle.find("stop") if vehicle is not None else None
    assert route is not None and route.get("edges") == "w0_c00"
    assert vehicle is not None and vehicle.get("departLane") == "1"
    assert stop is not None and stop.get("lane") == "w0_c00_1"


def test_nanjing_pickup_zones_have_capacity_and_waiting_config() -> None:
    zones = load_pickup_zones(SCENARIO_PATH)

    north_zone = next(zone for zone in zones if zone["id"] == "north_plaza_pickup")
    south_zone = next(zone for zone in zones if zone["id"] == "south_plaza_pickup")
    assert north_zone["capacity"] == 12
    assert north_zone["boarding_duration_s"] == 60
    assert north_zone["lane_id"] == "189391594#0_0"
    assert south_zone["capacity"] == 10
    assert south_zone["lane_id"] == "760767137#1_0"


def test_pickup_zone_additional_and_vehicle_stops_are_generated(tmp_path) -> None:
    route_file = SCENARIO_PATH / "routes" / "intersection.rou.xml"
    zones = load_pickup_zones(SCENARIO_PATH)
    additional_file = tmp_path / "pickup_zones.add.xml"

    write_pickup_zone_additional(additional_file, zones)
    additional_text = additional_file.read_text(encoding="utf-8")
    assert 'id="north_plaza_pickup"' in additional_text
    assert 'roadsideCapacity="12"' in additional_text

    tree = ET.parse(route_file)
    pickup_waiting = apply_pickup_stops_to_routes(tree.getroot(), zones)

    assert pickup_waiting["enabled"]
    assert pickup_waiting["total_stopped_vehicles"] > 0
    zone_counts = {
        zone["id"]: zone["matched_vehicle_count"]
        for zone in pickup_waiting["zones"]
    }
    assert zone_counts["north_plaza_pickup"] > 0
    assert zone_counts["south_plaza_pickup"] > 0
    assert any(
        stop.get("parkingArea") == "north_plaza_pickup"
        for vehicle in tree.getroot().findall("vehicle")
        for stop in vehicle.findall("stop")
    )
    assert any(
        stop.get("parkingArea") == "south_plaza_pickup"
        for vehicle in tree.getroot().findall("vehicle")
        for stop in vehicle.findall("stop")
    )
