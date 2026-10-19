from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any


PASSENGER_BLOCKED_CLASSES = {
    "passenger",
    "taxi",
}


def load_map_objects(scenario_path: Path, map_config: dict) -> tuple[list[dict], dict[str, list[dict]]]:
    net_file = scenario_path / str(map_config["net_file"])
    if map_config.get("coordinate_system") == "sumo_xy":
        node_file = scenario_path / str(map_config["node_file"])
        edge_file = scenario_path / str(map_config["edge_file"])
        edges = [
            dict(item)
            for item in _load_sumo_xy_edges(
                str(node_file.resolve()),
                str(edge_file.resolve()),
                float(map_config.get("origin_latitude", 31.0)),
                float(map_config.get("origin_longitude", 118.0)),
                float(map_config.get("meters_per_degree", 111_320)),
            )
        ]
    else:
        geo_edge_file = scenario_path / str(map_config["geo_edge_file"])
        edges = [dict(item) for item in _load_geo_edges(str(geo_edge_file.resolve()))]
    lanes_by_edge = {
        edge_id: [dict(lane) for lane in lanes]
        for edge_id, lanes in _load_lanes(str(net_file.resolve()))
    }
    edges = _apply_map_display_filter(edges, lanes_by_edge, str(net_file.resolve()), map_config)
    return edges, lanes_by_edge


@lru_cache(maxsize=8)
def _load_geo_edges(path_text: str) -> tuple[dict, ...]:
    root = ET.parse(path_text).getroot()
    edges: list[dict] = []
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        shape = edge.get("shape", "")
        if not edge_id or edge_id.startswith(":") or not shape:
            continue
        allow = set((edge.get("allow") or "").split())
        disallow = set((edge.get("disallow") or "").split())
        if allow and not allow.intersection(PASSENGER_BLOCKED_CLASSES):
            continue
        if "passenger" in disallow:
            continue
        coordinates: list[list[float]] = []
        try:
            for token in shape.split():
                longitude_text, latitude_text = token.split(",", 1)
                coordinates.append([float(longitude_text), float(latitude_text)])
        except ValueError:
            continue
        if len(coordinates) < 2:
            continue
        edges.append(
            {
                "edge_id": edge_id,
                "edge_name": edge.get("name") or "",
                "road_type": edge.get("type") or "",
                "lane_count": int(edge.get("numLanes") or 1),
                "speed_limit_mps": round(float(edge.get("speed") or 0), 2),
                "coordinates": coordinates,
                "from_node": edge.get("from") or "",
                "to_node": edge.get("to") or "",
            }
        )
    return tuple(edges)


@lru_cache(maxsize=8)
def _load_sumo_xy_edges(
    node_path_text: str,
    edge_path_text: str,
    origin_latitude: float,
    origin_longitude: float,
    meters_per_degree: float,
) -> tuple[dict, ...]:
    node_root = ET.parse(node_path_text).getroot()
    edge_root = ET.parse(edge_path_text).getroot()
    nodes = {
        node.get("id", ""): (float(node.get("x") or 0), float(node.get("y") or 0))
        for node in node_root.findall("node")
        if node.get("id")
    }
    edges: list[dict] = []
    for edge in edge_root.findall("edge"):
        edge_id = edge.get("id", "")
        from_node = edge.get("from", "")
        to_node = edge.get("to", "")
        if not edge_id or from_node not in nodes or to_node not in nodes:
            continue
        from_x, from_y = nodes[from_node]
        to_x, to_y = nodes[to_node]
        coordinates = [
            _sumo_xy_to_lon_lat(from_x, from_y, origin_latitude, origin_longitude, meters_per_degree),
            _sumo_xy_to_lon_lat(to_x, to_y, origin_latitude, origin_longitude, meters_per_degree),
        ]
        edges.append(
            {
                "edge_id": edge_id,
                "edge_name": _friendly_sumo_edge_name(edge_id),
                "road_type": "仿真道路",
                "lane_count": int(edge.get("numLanes") or 1),
                "speed_limit_mps": round(float(edge.get("speed") or 0), 2),
                "coordinates": coordinates,
                "from_node": from_node,
                "to_node": to_node,
            }
        )
    return tuple(edges)


def _sumo_xy_to_lon_lat(
    x: float,
    y: float,
    origin_latitude: float,
    origin_longitude: float,
    meters_per_degree: float,
) -> list[float]:
    return [
        origin_longitude + x / meters_per_degree,
        origin_latitude + y / meters_per_degree,
    ]


def _friendly_sumo_edge_name(edge_id: str) -> str:
    parts = edge_id.split("_", 1)
    if len(parts) != 2:
        return f"道路 {edge_id}"
    from_node, to_node = parts
    intersection_names = {
        "c00": "西北路口",
        "c10": "东北路口",
        "c01": "西南路口",
        "c11": "东南路口",
    }
    approach_labels = {
        "n0": "北进口",
        "n1": "北进口",
        "s0": "南进口",
        "s1": "南进口",
        "w0": "西进口",
        "w1": "西进口",
        "e0": "东进口",
        "e1": "东进口",
    }
    if to_node in intersection_names and from_node in approach_labels:
        return f"{intersection_names[to_node]}{approach_labels[from_node]}"
    if from_node in intersection_names and to_node in intersection_names:
        return f"{intersection_names[from_node]}至{intersection_names[to_node]}"
    if from_node in intersection_names:
        return f"{intersection_names[from_node]}出口道路"
    return f"道路 {edge_id}"


@lru_cache(maxsize=8)
def _load_lanes(path_text: str) -> tuple[tuple[str, tuple[dict, ...]], ...]:
    root = ET.parse(path_text).getroot()
    rows: list[tuple[str, tuple[dict, ...]]] = []
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if not edge_id or edge_id.startswith(":") or edge.get("function") == "internal":
            continue
        lanes = []
        for lane in edge.findall("lane"):
            lanes.append(
                {
                    "lane_id": lane.get("id", ""),
                    "index": int(lane.get("index") or 0),
                    "length_m": round(float(lane.get("length") or 0), 2),
                    "speed_limit_mps": round(float(lane.get("speed") or 0), 2),
                }
            )
        if lanes:
            rows.append((edge_id, tuple(lanes)))
    return tuple(rows)


def _apply_map_display_filter(
    edges: list[dict],
    lanes_by_edge: dict[str, list[dict]],
    net_path_text: str,
    map_config: dict,
) -> list[dict]:
    filter_config = map_config.get("display_filter") or {}
    if not filter_config.get("enabled"):
        return edges

    preserved_edge_ids = {
        str(zone.get("edge_id", "")).strip()
        for zone in map_config.get("pickup_zones") or []
        if zone.get("edge_id")
    }
    allowed_prefixes = tuple(filter_config.get("allowed_road_type_prefixes") or [])
    min_length_m = float(filter_config.get("min_length_m", 0) or 0)
    dead_end_edge_ids = (
        set(_load_dead_end_edge_ids(net_path_text))
        if filter_config.get("hide_dead_end_edges")
        else set()
    )

    prelim_edges: list[dict] = []
    for edge in edges:
        edge_id = edge.get("edge_id", "")
        if edge_id in preserved_edge_ids:
            prelim_edges.append(edge)
            continue
        if edge_id not in lanes_by_edge:
            continue
        road_type = str(edge.get("road_type") or "")
        if allowed_prefixes and not road_type.startswith(allowed_prefixes):
            continue
        if edge_id in dead_end_edge_ids:
            continue
        if min_length_m and _edge_length_m(edge.get("coordinates") or []) < min_length_m:
            continue
        prelim_edges.append(edge)

    leaf_edge_ids = (
        _iterative_leaf_edge_ids(prelim_edges, preserved_edge_ids)
        if filter_config.get("hide_leaf_edges")
        else set()
    )
    return [
        edge
        for edge in prelim_edges
        if edge.get("edge_id", "") in preserved_edge_ids or edge.get("edge_id", "") not in leaf_edge_ids
    ]


@lru_cache(maxsize=8)
def _load_dead_end_edge_ids(net_path_text: str) -> tuple[str, ...]:
    root = ET.parse(net_path_text).getroot()
    normal_edge_ids = {
        edge.get("id", "")
        for edge in root.findall("edge")
        if edge.get("id") and not edge.get("id", "").startswith(":") and edge.get("function") != "internal"
    }
    incoming: dict[str, int] = {edge_id: 0 for edge_id in normal_edge_ids}
    outgoing: dict[str, int] = {edge_id: 0 for edge_id in normal_edge_ids}
    for connection in root.findall("connection"):
        from_edge = connection.get("from", "")
        to_edge = connection.get("to", "")
        if from_edge in outgoing and to_edge in incoming:
            outgoing[from_edge] += 1
            incoming[to_edge] += 1
    return tuple(
        edge_id
        for edge_id in normal_edge_ids
        if incoming.get(edge_id, 0) == 0 or outgoing.get(edge_id, 0) == 0
    )


def _edge_length_m(coordinates: list[list[float]]) -> float:
    total = 0.0
    for start, end in zip(coordinates, coordinates[1:]):
        total += _geo_distance_m(start[0], start[1], end[0], end[1])
    return total


def _geo_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    mean_lat = math.radians((lat1 + lat2) / 2)
    dx = (lon1 - lon2) * 111_320 * math.cos(mean_lat)
    dy = (lat1 - lat2) * 110_540
    return math.hypot(dx, dy)


def _iterative_leaf_edge_ids(edges: list[dict], preserved_edge_ids: set[str]) -> set[str]:
    endpoints = {
        edge.get("edge_id", ""): (edge.get("from_node", ""), edge.get("to_node", ""))
        for edge in edges
        if edge.get("edge_id") and edge.get("from_node") and edge.get("to_node")
    }
    active_edge_ids = set(endpoints)
    removed: set[str] = set()
    changed = True
    while changed:
        changed = False
        degrees: dict[str, int] = {}
        for edge_id in active_edge_ids - removed:
            from_node, to_node = endpoints[edge_id]
            degrees[from_node] = degrees.get(from_node, 0) + 1
            degrees[to_node] = degrees.get(to_node, 0) + 1
        leaf_edge_ids = []
        for edge_id in active_edge_ids - removed:
            if edge_id in preserved_edge_ids:
                continue
            from_node, to_node = endpoints[edge_id]
            if degrees.get(from_node, 0) <= 1 or degrees.get(to_node, 0) <= 1:
                leaf_edge_ids.append(edge_id)
        if leaf_edge_ids:
            removed.update(leaf_edge_ids)
            changed = True
    return removed


def render_spatial_selector(scenario) -> dict:
    import folium
    import streamlit as st
    from streamlit_folium import st_folium

    map_config = scenario.map_config
    edges, lanes_by_edge = load_map_objects(scenario.path, map_config)
    selected = _selection_for_scenario(st.session_state.get("spatial_selection"), scenario.id)
    if selected:
        selected = _render_expanded_lane_cards(st, scenario, selected, lanes_by_edge)
    else:
        st.info("请在下方地图点击道路或上客区。选择道路后，这里会展开显示全部车道信息。")
    selected_key = selected.get("selector_key") if selected else None

    center = map_config.get("center") or [31.9688, 118.7985]
    fmap = folium.Map(
        location=center,
        zoom_start=int(map_config.get("zoom") or 14),
        tiles="CartoDB positron",
        control_scale=True,
        prefer_canvas=True,
    )

    edge_features = []
    object_lookup: dict[str, dict] = {}
    for edge in edges:
        selector_key = f"edge:{edge['edge_id']}"
        properties = {
            **edge,
            "selector_key": selector_key,
            "object_type": "road",
            "display_name": edge["edge_name"] or f"道路 {edge['edge_id']}",
            "selected": selector_key == selected_key,
        }
        properties.pop("coordinates", None)
        object_lookup[selector_key] = properties
        edge_features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "LineString", "coordinates": edge["coordinates"]},
            }
        )

    folium.GeoJson(
        {"type": "FeatureCollection", "features": edge_features},
        name="可通行道路",
        style_function=lambda feature: {
            "color": "#dc2626" if feature["properties"].get("selected") else "#1d4ed8",
            "weight": 7 if feature["properties"].get("selected") else 3,
            "opacity": 1 if feature["properties"].get("selected") else 0.58,
        },
        highlight_function=lambda _: {"color": "#f59e0b", "weight": 7, "opacity": 1},
        tooltip=folium.GeoJsonTooltip(
            fields=["display_name", "edge_id", "lane_count", "speed_limit_mps"],
            aliases=["道路", "道路 ID", "车道数", "限速（m/s）"],
            sticky=True,
        ),
        popup=folium.GeoJsonPopup(fields=["selector_key"], aliases=["选择标识"]),
    ).add_to(fmap)

    for zone in map_config.get("pickup_zones") or []:
        selector_key = f"zone:{zone['id']}"
        zone_selection = {
            **zone,
            "selector_key": selector_key,
            "object_type": "pickup_zone",
            "display_name": zone["name"],
        }
        object_lookup[selector_key] = zone_selection
        folium.CircleMarker(
            location=[zone["latitude"], zone["longitude"]],
            radius=12 if selector_key == selected_key else 9,
            color="#9a3412",
            weight=3,
            fill=True,
            fill_color="#f97316",
            fill_opacity=0.9,
            tooltip=f"{zone['name']}（点击选择）",
            popup=selector_key,
        ).add_to(fmap)

    folium.LayerControl(collapsed=True).add_to(fmap)
    map_state = st_folium(
        fmap,
        key=f"spatial_map_{scenario.id}",
        height=520,
        use_container_width=True,
        returned_objects=[
            "last_active_drawing",
            "last_object_clicked_popup",
            "last_object_clicked_tooltip",
        ],
    )

    clicked = _extract_clicked_object(map_state, object_lookup)
    if clicked and clicked.get("selector_key") != selected_key:
        selected = _complete_selection(clicked, lanes_by_edge, scenario)
        st.session_state.spatial_selection = selected
        st.rerun()

    selected = _selection_for_scenario(st.session_state.get("spatial_selection"), scenario.id)
    if not selected:
        st.caption("点击蓝色道路或橙色上客区。")
        return {}
    return dict(st.session_state.spatial_selection)


def render_generic_spatial_selector(scenario) -> dict:
    import streamlit as st

    if _is_topology_scenario(scenario):
        return render_topology_spatial_selector(scenario)

    selected = _selection_for_scenario(st.session_state.get("spatial_selection"), scenario.id)
    objects = build_generic_spatial_objects(scenario)
    if not objects:
        st.caption("当前场景尚未配置可选择的空间对象。")
        return {}

    intersection_options = list({item["intersection_id"]: item["intersection_name"] for item in objects}.items())
    current_intersection_id = selected.get("intersection_id") if selected else ""
    intersection_ids = [item[0] for item in intersection_options]
    intersection_index = intersection_ids.index(current_intersection_id) if current_intersection_id in intersection_ids else 0
    chosen_intersection_id = st.selectbox(
        "交叉口",
        options=intersection_ids,
        index=intersection_index,
        format_func=lambda item_id: dict(intersection_options).get(item_id, item_id),
        key=f"generic_spatial_intersection_{scenario.id}",
    )

    approach_objects = [item for item in objects if item["intersection_id"] == chosen_intersection_id]
    approach_ids = [item["approach_key"] for item in approach_objects]
    current_approach = selected.get("approach_key") if selected else ""
    approach_index = approach_ids.index(current_approach) if current_approach in approach_ids else 0
    chosen_approach = st.selectbox(
        "进口方向",
        options=approach_ids,
        index=approach_index,
        format_func=lambda key: next(item["approach_label"] for item in approach_objects if item["approach_key"] == key),
        key=f"generic_spatial_approach_{scenario.id}_{chosen_intersection_id}",
    )

    approach_object = next(item for item in approach_objects if item["approach_key"] == chosen_approach)
    lane_options = approach_object["lanes"]
    lane_ids = [lane["lane_id"] for lane in lane_options]
    current_lane = selected.get("lane_id") if selected else ""
    lane_index = lane_ids.index(current_lane) if current_lane in lane_ids else min(1, len(lane_ids) - 1)
    chosen_lane_id = st.selectbox(
        "具体车道",
        options=lane_ids,
        index=lane_index,
        format_func=lambda lane_id: _format_generic_lane_option(lane_id, lane_options),
        key=f"generic_spatial_lane_{scenario.id}_{approach_object['edge_id']}",
    )
    chosen_lane = next(lane for lane in lane_options if lane["lane_id"] == chosen_lane_id)

    selection = {
        "scenario_id": scenario.id,
        "selector_key": f"generic:{scenario.id}:{approach_object['edge_id']}:{chosen_lane_id}",
        "object_type": "intersection_lane",
        "display_name": (
            f"{approach_object['intersection_name']}"
            f"{approach_object['approach_label']}"
            f"{chosen_lane['movement_label']}车道"
        ),
        "intersection_id": approach_object["intersection_id"],
        "intersection_name": approach_object["intersection_name"],
        "approach_key": approach_object["approach_key"],
        "approach_label": approach_object["approach_label"],
        "movement_key": chosen_lane["movement_key"],
        "movement_label": chosen_lane["movement_label"],
        "edge_id": approach_object["edge_id"],
        "lane_id": chosen_lane_id,
        "lane_ids": lane_ids,
    }
    if selection != selected:
        st.session_state.spatial_selection = selection

    info_col, action_col = st.columns([4, 1])
    with info_col:
        st.success(
            f"已选择空间对象：**{selection['display_name']}**  \n"
            f"进口边：`{selection['edge_id']}`；车道：`{selection['lane_id']}`"
        )
    with action_col:
        if st.button("清除选择", use_container_width=True, key=f"generic_spatial_clear_{scenario.id}"):
            st.session_state.spatial_selection = {}
            st.rerun()
    return dict(st.session_state.spatial_selection)


def render_topology_spatial_selector(scenario) -> dict:
    import streamlit as st

    objects = build_generic_spatial_objects(scenario)
    if not objects:
        st.caption("当前场景尚未配置可视化拓扑对象。")
        return {}

    selected = _selection_for_scenario(st.session_state.get("spatial_selection"), scenario.id)
    objects_by_intersection = _objects_by_intersection(objects)
    clicked_object = None

    st.markdown("**四交叉口拓扑图（点击进口方向）**")
    st.caption("上方为北，下方为南；每个路口周围的按钮代表该路口的进口方向。")

    for row in (("c00", "c10"), ("c01", "c11")):
        cols = st.columns(2)
        for col, intersection_id in zip(cols, row):
            with col:
                clicked = _render_topology_intersection_card(
                    scenario.id,
                    intersection_id,
                    objects_by_intersection.get(intersection_id, []),
                    selected,
                )
                if clicked:
                    clicked_object = clicked

    if clicked_object:
        selected = build_topology_selection(scenario.id, clicked_object)
        st.session_state.spatial_selection = selected

    selected = _selection_for_scenario(st.session_state.get("spatial_selection"), scenario.id)
    if not selected:
        st.info("请先在拓扑图中选择一个路口进口。")
        return {}

    selected_object = _find_object_for_selection(objects, selected)
    if not selected_object:
        st.session_state.spatial_selection = {}
        st.info("当前选择已失效，请重新选择一个进口。")
        return {}

    lane_cols = st.columns(len(selected_object["lanes"]))
    for col, lane in zip(lane_cols, selected_object["lanes"]):
        is_lane_selected = lane["lane_id"] == selected.get("lane_id")
        with col:
            if st.button(
                f"{lane['movement_label']}车道",
                key=f"topology_lane_{scenario.id}_{lane['lane_id']}",
                type="primary" if is_lane_selected else "secondary",
                use_container_width=True,
            ):
                selected = build_topology_selection(scenario.id, selected_object, lane["lane_id"])
                st.session_state.spatial_selection = selected

    selected = _selection_for_scenario(st.session_state.get("spatial_selection"), scenario.id)
    info_col, action_col = st.columns([4, 1])
    with info_col:
        st.success(
            f"已选择空间对象：**{selected['display_name']}**  \n"
            f"进口边：`{selected['edge_id']}`；车道：`{selected['lane_id']}`"
        )
    with action_col:
        if st.button("清除选择", use_container_width=True, key=f"topology_spatial_clear_{scenario.id}"):
            st.session_state.spatial_selection = {}
            st.rerun()
    return dict(st.session_state.spatial_selection)


def build_generic_spatial_objects(scenario) -> list[dict]:
    if not getattr(scenario, "intersections", None):
        return []
    net_file = scenario.path / "network" / "intersection.net.xml"
    if not net_file.exists():
        return []
    lanes_by_edge = {
        edge_id: [dict(lane) for lane in lanes]
        for edge_id, lanes in _load_lanes(str(net_file.resolve()))
    }
    objects: list[dict] = []
    for intersection in scenario.intersections:
        intersection_id = str(intersection.get("id", ""))
        intersection_name = str(intersection.get("name") or intersection_id)
        for approach_key, approach_label in _APPROACH_OPTIONS:
            edge_id = _infer_incoming_edge_id(intersection_id, approach_key)
            lanes = lanes_by_edge.get(edge_id, [])
            if not lanes:
                continue
            objects.append(
                {
                    "intersection_id": intersection_id,
                    "intersection_name": intersection_name,
                    "approach_key": approach_key,
                    "approach_label": approach_label,
                    "edge_id": edge_id,
                    "lanes": _with_movement_labels(lanes),
                }
            )
    return objects


def build_topology_selection(scenario_id: str, approach_object: dict, lane_id: str | None = None) -> dict:
    lane_ids = [lane["lane_id"] for lane in approach_object["lanes"]]
    selected_lane_id = lane_id if lane_id in lane_ids else _default_topology_lane_id(approach_object["lanes"])
    selected_lane = next(lane for lane in approach_object["lanes"] if lane["lane_id"] == selected_lane_id)
    return {
        "scenario_id": scenario_id,
        "selector_key": f"topology:{scenario_id}:{approach_object['edge_id']}:{selected_lane_id}",
        "object_type": "intersection_lane",
        "display_name": (
            f"{approach_object['intersection_name']}"
            f"{approach_object['approach_label']}"
            f"{selected_lane['movement_label']}车道"
        ),
        "intersection_id": approach_object["intersection_id"],
        "intersection_name": approach_object["intersection_name"],
        "approach_key": approach_object["approach_key"],
        "approach_label": approach_object["approach_label"],
        "movement_key": selected_lane["movement_key"],
        "movement_label": selected_lane["movement_label"],
        "edge_id": approach_object["edge_id"],
        "lane_id": selected_lane_id,
        "lane_ids": lane_ids,
    }


def build_spatial_context(selection: dict) -> str:
    if not selection:
        return ""
    lane_ids = ",".join(selection.get("lane_ids") or [])
    return "\n".join(
        [
            "SimTrend空间精确定位（优先于自然语言中的模糊位置）：",
            f"- 地图对象类型：{selection.get('object_type', 'road')}",
            f"- 地图对象名称：{selection.get('display_name', '未命名道路')}",
            f"- 地图道路ID：{selection.get('edge_id', '')}",
            f"- 地图车道ID：{selection.get('lane_id', '')}",
            f"- 地图道路全部车道：{lane_ids}",
        ]
    )


def selection_summary(selection: dict) -> str:
    if not selection:
        return ""
    if selection.get("object_type") == "pickup_zone":
        object_label = "上客区"
    elif selection.get("object_type") == "intersection_lane":
        object_label = "交叉口车道"
    else:
        object_label = "道路/车道"
    return (
        f"{object_label}：{selection.get('display_name', '未命名道路')}；"
        f"道路 `{selection.get('edge_id', '-')}`；车道 `{selection.get('lane_id', '-')}`"
    )


def _selection_for_scenario(value: Any, scenario_id: str) -> dict:
    if isinstance(value, dict) and value.get("scenario_id") == scenario_id:
        return value
    return {}


def _extract_clicked_object(map_state: dict | None, object_lookup: dict[str, dict]) -> dict:
    if not map_state:
        return {}
    feature = map_state.get("last_active_drawing")
    if isinstance(feature, dict):
        properties = feature.get("properties")
        if isinstance(properties, dict):
            selector_key = properties.get("selector_key")
            if selector_key in object_lookup:
                return object_lookup[selector_key]
    for field in ("last_object_clicked_popup", "last_object_clicked_tooltip"):
        value = map_state.get(field)
        if isinstance(value, str):
            if value in object_lookup:
                return object_lookup[value]
            for selector_key in object_lookup:
                if selector_key in value:
                    return object_lookup[selector_key]
    return {}


def _render_expanded_lane_cards(st, scenario, selected: dict, lanes_by_edge: dict[str, list[dict]]) -> dict:
    edge_id = selected.get("edge_id", "")
    lane_options = sorted(lanes_by_edge.get(edge_id, []), key=lambda item: item.get("index", 0))
    edge_display_name = selected.get("edge_display_name") or selected.get("display_name") or f"道路 {edge_id}"

    title_column, clear_column = st.columns([5, 1])
    with title_column:
        object_label = "网约车上客区" if selected.get("object_type") == "pickup_zone" else "当前道路"
        st.markdown(f"**{object_label}：{edge_display_name}**")
        road_details = [f"道路 ID：`{edge_id or '-'}`"]
        if selected.get("road_type"):
            road_details.append(f"类型：{selected['road_type']}")
        if selected.get("lane_count"):
            road_details.append(f"车道数：{selected['lane_count']}")
        if selected.get("speed_limit_mps") is not None:
            road_details.append(f"道路限速：{float(selected['speed_limit_mps']):.1f} m/s")
        st.caption("；".join(road_details))
    with clear_column:
        if st.button(
            "清除选择",
            key=f"clear_spatial_selection_{scenario.id}",
            use_container_width=True,
        ):
            st.session_state.spatial_selection = {}
            st.rerun()

    if selected.get("object_type") == "pickup_zone":
        st.success(
            f"已选择上客区绑定车道：`{selected.get('lane_id', '-')}`；"
            f"容量：{selected.get('capacity', 0)}；平均停靠：{selected.get('boarding_duration_s', 0)} 秒。"
        )
        if selected.get("description"):
            st.caption(str(selected["description"]))
        return selected

    if not lane_options:
        st.warning("该道路没有可供选择的机动车道。")
        return selected

    st.markdown("**选择具体车道**")
    lane_ids = [lane["lane_id"] for lane in lane_options]
    current_lane_id = selected.get("lane_id", "")
    for lane in lane_options:
        lane_id = lane["lane_id"]
        movement_key, movement_label = _map_lane_movement(scenario, selected, lane, lane_options)
        is_selected = lane_id == current_lane_id
        with st.container(border=True):
            detail_column, action_column = st.columns([5, 1])
            with detail_column:
                st.markdown(f"**{movement_label}**")
                st.caption(
                    f"车道 ID：`{lane_id}`；车道序号：{int(lane.get('index', 0)) + 1}；"
                    f"长度：{float(lane.get('length_m', 0)):.1f} m；"
                    f"限速：{float(lane.get('speed_limit_mps', 0)):.1f} m/s"
                )
            with action_column:
                if st.button(
                    "已选择" if is_selected else "选择车道",
                    key=f"expanded_spatial_lane_{scenario.id}_{edge_id}_{lane_id}",
                    type="primary" if is_selected else "secondary",
                    use_container_width=True,
                ) and not is_selected:
                    display_name = (
                        f"{edge_display_name}{movement_label}"
                        if movement_key
                        else f"{edge_display_name}·{movement_label}"
                    )
                    updated = {
                        **selected,
                        "edge_display_name": edge_display_name,
                        "display_name": display_name,
                        "lane_id": lane_id,
                        "lane_ids": lane_ids,
                        "movement_key": movement_key,
                        "movement_label": movement_label.removesuffix("车道"),
                    }
                    st.session_state.spatial_selection = updated
                    st.rerun()

    st.success(
        f"当前任务位置：**{selected.get('display_name', edge_display_name)}**；"
        f"道路 ID：`{edge_id}`；车道 ID：`{current_lane_id or '-'}`。"
    )
    return selected


def _complete_selection(clicked: dict, lanes_by_edge: dict[str, list[dict]], scenario) -> dict:
    edge_id = clicked.get("edge_id", "")
    lanes = sorted(lanes_by_edge.get(edge_id, []), key=lambda item: item.get("index", 0))
    lane_ids = [lane["lane_id"] for lane in lanes]
    lane_id = clicked.get("lane_id") or _default_map_lane_id(scenario, clicked, lanes)
    selected_lane = next((lane for lane in lanes if lane["lane_id"] == lane_id), {})
    movement_key, movement_label = _map_lane_movement(scenario, clicked, selected_lane, lanes)
    edge_display_name = clicked.get("display_name") or f"道路 {edge_id}"
    display_name = edge_display_name
    if clicked.get("object_type") != "pickup_zone" and lane_id:
        display_name = (
            f"{edge_display_name}{movement_label}"
            if movement_key
            else f"{edge_display_name}·{movement_label}"
        )
    return {
        **clicked,
        "scenario_id": scenario.id,
        "edge_display_name": edge_display_name,
        "display_name": display_name,
        "edge_id": edge_id,
        "lane_id": lane_id,
        "lane_ids": lane_ids,
        "movement_key": movement_key,
        "movement_label": movement_label.removesuffix("车道"),
    }


def _default_map_lane_id(scenario, edge: dict, lanes: list[dict]) -> str:
    if not lanes:
        return ""
    if _is_four_intersection_incoming_edge(scenario, edge):
        through_lane = next((lane for lane in lanes if int(lane.get("index", 0)) == 1), None)
        if through_lane:
            return through_lane["lane_id"]
    return lanes[0]["lane_id"]


def _map_lane_movement(
    scenario,
    edge: dict,
    lane: dict,
    all_lanes: list[dict],
) -> tuple[str | None, str]:
    lane_index = int(lane.get("index", 0))
    if _is_four_intersection_incoming_edge(scenario, edge) and len(all_lanes) >= 3:
        movement_key, movement_label = _MOVEMENT_BY_LANE_INDEX.get(
            lane_index,
            (f"lane_{lane_index}", f"第 {lane_index + 1} 车道"),
        )
        return movement_key, f"{movement_label}车道"
    return None, f"车道 {lane_index + 1}"


def _is_four_intersection_incoming_edge(scenario, edge: dict) -> bool:
    return _is_topology_scenario(scenario) and edge.get("to_node") in {"c00", "c10", "c01", "c11"}


_APPROACH_OPTIONS = [
    ("east", "东进口"),
    ("west", "西进口"),
    ("south", "南进口"),
    ("north", "北进口"),
]

_MOVEMENT_BY_LANE_INDEX = {
    0: ("left", "左转"),
    1: ("through", "直行"),
    2: ("right", "右转"),
}

_FOUR_INTERSECTION_INCOMING_FROM = {
    "c00": {"north": "n0", "south": "c01", "west": "w0", "east": "c10"},
    "c10": {"north": "n1", "south": "c11", "west": "c00", "east": "e0"},
    "c01": {"north": "c00", "south": "s0", "west": "w1", "east": "c11"},
    "c11": {"north": "c10", "south": "s1", "west": "c01", "east": "e1"},
}


def _infer_incoming_edge_id(intersection_id: str, approach_key: str) -> str:
    incoming_from = _FOUR_INTERSECTION_INCOMING_FROM.get(intersection_id, {}).get(approach_key)
    if incoming_from:
        return f"{incoming_from}_{intersection_id}"
    return ""


def _with_movement_labels(lanes: list[dict]) -> list[dict]:
    enriched = []
    for lane in sorted(lanes, key=lambda item: item.get("index", 0)):
        movement_key, movement_label = _MOVEMENT_BY_LANE_INDEX.get(
            int(lane.get("index", 0)),
            (f"lane_{lane.get('index', 0)}", f"第{int(lane.get('index', 0)) + 1}"),
        )
        enriched.append({**lane, "movement_key": movement_key, "movement_label": movement_label})
    return enriched


def _format_generic_lane_option(lane_id: str, lanes: list[dict]) -> str:
    lane = next((item for item in lanes if item["lane_id"] == lane_id), {})
    return (
        f"{lane.get('movement_label', '车道')}车道 · {lane_id} · "
        f"长度 {lane.get('length_m', 0):.0f} m"
    )


def _is_topology_scenario(scenario) -> bool:
    scenario_id = str(getattr(scenario, "id", ""))
    return scenario_id in {"four_intersections", "four_intersections_light"}


def _objects_by_intersection(objects: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in objects:
        grouped.setdefault(item["intersection_id"], []).append(item)
    return grouped


def _render_topology_intersection_card(
    scenario_id: str,
    intersection_id: str,
    objects: list[dict],
    selected: dict,
) -> dict | None:
    import streamlit as st

    if not objects:
        return None
    name = objects[0]["intersection_name"]
    by_approach = {item["approach_key"]: item for item in objects}
    st.markdown(f"##### {name}")

    clicked = None
    top_cols = st.columns([1, 1, 1])
    with top_cols[1]:
        clicked = _approach_button(scenario_id, by_approach, "north", selected) or clicked

    mid_cols = st.columns([1, 1, 1])
    with mid_cols[0]:
        clicked = _approach_button(scenario_id, by_approach, "west", selected) or clicked
    with mid_cols[1]:
        st.markdown(
            "<div style='height:42px;border-radius:12px;background:#eef2ff;"
            "border:1px solid #c7d2fe;text-align:center;line-height:42px;"
            "font-weight:700;color:#1e3a8a;'>路口</div>",
            unsafe_allow_html=True,
        )
    with mid_cols[2]:
        clicked = _approach_button(scenario_id, by_approach, "east", selected) or clicked

    bottom_cols = st.columns([1, 1, 1])
    with bottom_cols[1]:
        clicked = _approach_button(scenario_id, by_approach, "south", selected) or clicked
    st.divider()
    return clicked


def _approach_button(
    scenario_id: str,
    by_approach: dict[str, dict],
    approach_key: str,
    selected: dict,
) -> dict | None:
    import streamlit as st

    approach = by_approach.get(approach_key)
    if not approach:
        st.caption("-")
        return None
    is_selected = (
        selected.get("intersection_id") == approach["intersection_id"]
        and selected.get("approach_key") == approach_key
    )
    if st.button(
        approach["approach_label"],
        key=f"topology_approach_{scenario_id}_{approach['intersection_id']}_{approach_key}",
        type="primary" if is_selected else "secondary",
        use_container_width=True,
    ):
        return approach
    return None


def _find_object_for_selection(objects: list[dict], selected: dict) -> dict | None:
    for item in objects:
        if item["edge_id"] == selected.get("edge_id"):
            return item
    return None


def _default_topology_lane_id(lanes: list[dict]) -> str:
    through_lane = next((lane for lane in lanes if lane.get("movement_key") == "through"), None)
    if through_lane:
        return through_lane["lane_id"]
    return lanes[0]["lane_id"]
