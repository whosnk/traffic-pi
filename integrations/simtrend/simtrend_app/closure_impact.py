from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def analyze_closure_impact(
    route_file: str | Path,
    net_file: str | Path,
    incident_context: dict,
    duration_seconds: int,
) -> dict:
    routes_root = ET.parse(Path(route_file)).getroot()
    return analyze_closure_impact_root(
        routes_root,
        Path(net_file),
        incident_context,
        duration_seconds,
    )


def analyze_closure_impact_root(
    routes_root: ET.Element,
    net_file: Path,
    incident_context: dict,
    duration_seconds: int,
) -> dict:
    duration_seconds = max(int(duration_seconds), 1)
    incident_applies = bool(
        incident_context.get("apply_scene_edit")
        or incident_context.get("blocked_lane_id")
        or incident_context.get("blocked_edge_id")
        or incident_context.get("closed_lane_ids")
    )
    closed_lane_ids = [
        str(lane_id)
        for lane_id in (
            incident_context.get("closed_lane_ids")
            or [incident_context.get("blocked_lane_id", "")]
        )
        if lane_id
    ]
    blocked_edge_id = str(incident_context.get("blocked_edge_id") or "")
    if not blocked_edge_id and closed_lane_ids:
        blocked_edge_id = closed_lane_ids[0].rsplit("_", 1)[0]
    requested_overlay_route_edges = str(incident_context.get("route_edges") or "").split()
    effective_overlay_route_edges = resolve_incident_overlay_route(incident_context).split()
    overlay_route_consistent = bool(
        blocked_edge_id and blocked_edge_id in requested_overlay_route_edges
    )
    overlay_route_normalized = bool(
        blocked_edge_id and requested_overlay_route_edges != effective_overlay_route_edges
    )

    empty_result = {
        "enabled": False,
        "blocked_edge_id": blocked_edge_id,
        "closed_lane_ids": closed_lane_ids,
        "closure_start_s": 0,
        "closure_end_s": 0,
        "full_edge_closure": False,
        "requested_overlay_route_edges": requested_overlay_route_edges,
        "effective_overlay_route_edges": effective_overlay_route_edges,
        "overlay_route_consistent": overlay_route_consistent,
        "overlay_route_normalized": overlay_route_normalized,
        "affected_route_ids": [],
        "affected_flow_ids": [],
        "affected_vehicle_ids": [],
        "removed_flow_ids": [],
        "delayed_flow_ids": [],
        "removed_vehicle_ids": [],
        "delayed_vehicle_ids": [],
        "requires_mitigation": False,
        "simulation_can_proceed": True,
        "handling_mode": "no_action",
        "counts": {
            "routes": len(routes_root.findall("route")),
            "flows": len(routes_root.findall("flow")),
            "vehicles": len(routes_root.findall("vehicle")),
        },
        "note": "当前任务未启用车道封闭，无需执行封道可行性处置。",
    }
    if not incident_applies or not blocked_edge_id or not closed_lane_ids:
        return empty_result

    closure_end_s = min(
        max(int(incident_context.get("incident_duration_minutes", 0) or 0) * 60, 60),
        duration_seconds,
    )
    route_analysis = _find_routes_blocked_by_closure(
        routes_root,
        net_file,
        blocked_edge_id,
        closed_lane_ids,
    )
    affected_route_ids = route_analysis["route_ids"]
    affected_route_id_set = set(affected_route_ids)
    affected_vehicle_ids = route_analysis["vehicle_ids"]
    affected_vehicle_id_set = set(affected_vehicle_ids)

    affected_flow_ids: list[str] = []
    removed_flow_ids: list[str] = []
    delayed_flow_ids: list[str] = []
    for flow in routes_root.findall("flow"):
        if flow.get("route") not in affected_route_id_set:
            continue
        flow_id = flow.get("id", "")
        begin = _parse_float(flow.get("begin"), 0.0)
        end = _parse_float(flow.get("end"), float(duration_seconds))
        if begin >= closure_end_s:
            continue
        if flow_id:
            affected_flow_ids.append(flow_id)
        if end <= closure_end_s or closure_end_s >= duration_seconds:
            if flow_id:
                removed_flow_ids.append(flow_id)
        elif flow_id:
            delayed_flow_ids.append(flow_id)

    removed_vehicle_ids: list[str] = []
    delayed_vehicle_ids: list[str] = []
    for vehicle in routes_root.findall("vehicle"):
        vehicle_id = vehicle.get("id", "")
        if vehicle_id not in affected_vehicle_id_set:
            continue
        depart = _parse_float(vehicle.get("depart"), 0.0)
        if depart >= closure_end_s:
            continue
        if closure_end_s >= duration_seconds:
            removed_vehicle_ids.append(vehicle_id)
        else:
            delayed_vehicle_ids.append(vehicle_id)

    removal_count = len(removed_flow_ids) + len(removed_vehicle_ids)
    delay_count = len(delayed_flow_ids) + len(delayed_vehicle_ids)
    if removal_count and delay_count:
        handling_mode = "remove_and_delay"
    elif removal_count:
        handling_mode = "remove_during_closure"
    elif delay_count:
        handling_mode = "delay_until_reopen"
    else:
        handling_mode = "no_action"

    requires_mitigation = bool(removal_count or delay_count)
    if requires_mitigation:
        note = (
            f"预检发现封道影响 {len(affected_route_ids)} 条路线、"
            f"{len(affected_flow_ids)} 条车流和 {len(affected_vehicle_ids)} 辆显式车辆；"
            f"计划移除 {len(removed_flow_ids)} 条车流和 {len(removed_vehicle_ids)} 辆车，"
            f"延后 {len(delayed_flow_ids)} 条车流和 {len(delayed_vehicle_ids)} 辆车。"
        )
    else:
        note = "封闭车道不会阻断当前交通需求中的既定路径，可直接运行仿真。"
    if overlay_route_normalized:
        note += f"事故占道车辆路线已自动归一化为封闭路段 {blocked_edge_id}。"

    return {
        "enabled": True,
        "blocked_edge_id": blocked_edge_id,
        "closed_lane_ids": closed_lane_ids,
        "closure_start_s": 0,
        "closure_end_s": closure_end_s,
        "full_edge_closure": route_analysis["full_edge_closure"],
        "requested_overlay_route_edges": requested_overlay_route_edges,
        "effective_overlay_route_edges": effective_overlay_route_edges,
        "overlay_route_consistent": overlay_route_consistent,
        "overlay_route_normalized": overlay_route_normalized,
        "affected_route_ids": affected_route_ids,
        "affected_flow_ids": affected_flow_ids,
        "affected_vehicle_ids": affected_vehicle_ids,
        "removed_flow_ids": removed_flow_ids,
        "delayed_flow_ids": delayed_flow_ids,
        "removed_vehicle_ids": removed_vehicle_ids,
        "delayed_vehicle_ids": delayed_vehicle_ids,
        "requires_mitigation": requires_mitigation,
        "simulation_can_proceed": True,
        "handling_mode": handling_mode,
        "counts": {
            "routes": len(routes_root.findall("route")),
            "flows": len(routes_root.findall("flow")),
            "vehicles": len(routes_root.findall("vehicle")),
        },
        "note": note,
    }


def resolve_incident_overlay_route(incident_context: dict) -> str:
    blocked_edge_id = str(incident_context.get("blocked_edge_id") or "")
    if not blocked_edge_id:
        lane_id = str(incident_context.get("blocked_lane_id") or "")
        if "_" in lane_id:
            blocked_edge_id = lane_id.rsplit("_", 1)[0]
    return blocked_edge_id or str(incident_context.get("route_edges") or "")


def _find_routes_blocked_by_closure(
    routes_root: ET.Element,
    net_file: Path,
    blocked_edge_id: str,
    closed_lane_ids: list[str],
) -> dict:
    closed_lane_indices = {
        lane_id.rsplit("_", 1)[1]
        for lane_id in closed_lane_ids
        if lane_id.startswith(f"{blocked_edge_id}_") and "_" in lane_id
    }
    if not closed_lane_indices:
        return {"route_ids": [], "vehicle_ids": [], "full_edge_closure": False}

    connection_source_lanes, connection_destination_lanes = _load_connection_lane_indices(net_file)
    edge_lane_indices = _load_edge_lane_indices(net_file)
    all_blocked_edge_lanes = edge_lane_indices.get(blocked_edge_id, set())
    full_edge_closure = bool(all_blocked_edge_lanes) and all_blocked_edge_lanes.issubset(
        closed_lane_indices
    )
    affected_route_ids: list[str] = []
    route_edges_by_id: dict[str, list[str]] = {}
    for route in routes_root.findall("route"):
        route_id = route.get("id", "")
        edges = (route.get("edges") or "").split()
        route_edges_by_id[route_id] = edges
        if _route_is_blocked(
            edges,
            blocked_edge_id,
            closed_lane_indices,
            connection_source_lanes,
            connection_destination_lanes,
            full_edge_closure,
        ):
            affected_route_ids.append(route_id)

    affected_route_id_set = set(affected_route_ids)
    affected_vehicle_ids: list[str] = []
    for vehicle in routes_root.findall("vehicle"):
        route_ref = vehicle.get("route", "")
        inline_route = vehicle.find("route")
        edges = (
            (inline_route.get("edges") or "").split()
            if inline_route is not None
            else route_edges_by_id.get(route_ref, [])
        )
        if route_ref in affected_route_id_set or _route_is_blocked(
            edges,
            blocked_edge_id,
            closed_lane_indices,
            connection_source_lanes,
            connection_destination_lanes,
            full_edge_closure,
        ):
            vehicle_id = vehicle.get("id", "")
            if vehicle_id:
                affected_vehicle_ids.append(vehicle_id)

    return {
        "route_ids": affected_route_ids,
        "vehicle_ids": affected_vehicle_ids,
        "full_edge_closure": full_edge_closure,
    }


def _route_is_blocked(
    edges: list[str],
    blocked_edge_id: str,
    closed_lane_indices: set[str],
    connection_source_lanes: dict[tuple[str, str], set[str]],
    connection_destination_lanes: dict[tuple[str, str], set[str]],
    full_edge_closure: bool,
) -> bool:
    for index, edge_id in enumerate(edges):
        if edge_id != blocked_edge_id:
            continue
        if full_edge_closure:
            return True
        if index > 0:
            previous_edge = edges[index - 1]
            destination_lanes = connection_destination_lanes.get((previous_edge, edge_id), set())
            if destination_lanes and destination_lanes.issubset(closed_lane_indices):
                return True
        if index + 1 >= len(edges):
            continue
        next_edge = edges[index + 1]
        source_lanes = connection_source_lanes.get((edge_id, next_edge), set())
        if source_lanes and source_lanes.issubset(closed_lane_indices):
            return True
    return False


def _load_connection_lane_indices(
    net_file: Path,
) -> tuple[dict[tuple[str, str], set[str]], dict[tuple[str, str], set[str]]]:
    root = ET.parse(net_file).getroot()
    source_lanes: dict[tuple[str, str], set[str]] = {}
    destination_lanes: dict[tuple[str, str], set[str]] = {}
    for connection in root.findall("connection"):
        from_edge = connection.get("from")
        to_edge = connection.get("to")
        if not from_edge or not to_edge:
            continue
        edge_pair = (from_edge, to_edge)
        if connection.get("fromLane") is not None:
            source_lanes.setdefault(edge_pair, set()).add(connection.get("fromLane", ""))
        if connection.get("toLane") is not None:
            destination_lanes.setdefault(edge_pair, set()).add(connection.get("toLane", ""))
    return source_lanes, destination_lanes


def _load_edge_lane_indices(net_file: Path) -> dict[str, set[str]]:
    root = ET.parse(net_file).getroot()
    return {
        edge.get("id", ""): {
            lane.get("index", "")
            for lane in edge.findall("lane")
            if lane.get("index") is not None
        }
        for edge in root.findall("edge")
        if edge.get("id") and not edge.get("id", "").startswith(":")
    }


def _parse_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
