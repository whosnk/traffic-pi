from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from simtrend_app.tool_scripts.common import (
    DEFAULT_DEMAND_PROFILES,
    infer_demand_profile,
    normalize_duration,
    save_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build reference and adjusted traffic demand profiles.")
    parser.add_argument("--request-text", required=True)
    parser.add_argument("--duration-seconds", type=int, default=300)
    parser.add_argument("--project-dir", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    save_json(
        args.output,
        build_demand_plan(
            args.request_text,
            args.duration_seconds,
            Path(args.project_dir).resolve() if args.project_dir else None,
        ),
    )


def build_demand_plan(
    request_text: str,
    duration_seconds: int = 300,
    project_dir: Path | None = None,
) -> dict:
    adjusted_profile = infer_demand_profile(request_text)
    if project_dir and adjusted_profile.get("spatial_scope"):
        adjusted_profile = _resolve_spatial_scope(adjusted_profile, project_dir)
    reference_profile = dict(DEFAULT_DEMAND_PROFILES["standard"])
    duration = normalize_duration(duration_seconds)
    target = str(adjusted_profile.get("target") or "all")
    target_labels = {
        "ride_hailing_in": "网约车到站流量",
        "ride_hailing_out": "网约车离站流量",
        "ride_hailing_all": "全部网约车流量",
        "background": "背景社会车辆流量",
        "all": "全部交通流量",
    }

    time_start = int(adjusted_profile.get("time_window_start_s", 0) or 0)
    time_end = int(adjusted_profile.get("time_window_end_s", duration) or duration)
    return {
        "workflow_type": "demand_impact_evaluation",
        "request_text": request_text,
        "duration_seconds": duration,
        "target": target,
        "target_label": target_labels.get(target, target),
        "reference_profile": reference_profile,
        "adjusted_profile": adjusted_profile,
        "adjustment_scope": {
            "time_window_start_s": time_start,
            "time_window_end_s": time_end,
            "spatial_scope": adjusted_profile.get("spatial_scope") or "all",
            "spatial_scope_label": adjusted_profile.get("spatial_scope_label") or "整个场景",
            "spatial_edge_ids": adjusted_profile.get("spatial_edge_ids") or [],
            "spatial_match_mode": adjusted_profile.get("spatial_match_mode") or "all",
        },
        "controlled_variables": [
            "路网文件",
            "信号控制方案",
            "车辆路径分布",
            "仿真时长",
            "上客区配置",
        ],
        "changed_variable": "交通需求配置",
    }


def _resolve_spatial_scope(profile: dict, project_dir: Path) -> dict:
    scenario_file = project_dir / "scenario.json"
    net_file = project_dir / "network" / "intersection.net.xml"
    if not scenario_file.exists() or not net_file.exists():
        raise FileNotFoundError("当前场景缺少空间需求定位所需的 scenario.json 或路网文件。")
    scenario = json.loads(scenario_file.read_text(encoding="utf-8-sig"))
    scope = str(profile.get("spatial_scope") or "")
    scope_keyword = "北广场" if scope == "north_plaza" else "南广场" if scope == "south_plaza" else ""
    zones = scenario.get("map", {}).get("pickup_zones", [])
    matched_zones = [zone for zone in zones if scope_keyword and scope_keyword in str(zone.get("name", ""))]
    if not matched_zones:
        raise ValueError(f"当前场景未找到与 `{profile.get('spatial_scope_label', scope)}` 对应的上客区。")

    zone_edge_ids = {str(zone.get("edge_id")) for zone in matched_zones if zone.get("edge_id")}
    spatial_edge_ids = set(zone_edge_ids)
    root = ET.parse(net_file).getroot()
    for connection in root.findall("connection"):
        from_edge = str(connection.get("from") or "")
        to_edge = str(connection.get("to") or "")
        if from_edge in zone_edge_ids and to_edge and not to_edge.startswith(":"):
            spatial_edge_ids.add(to_edge)
        if to_edge in zone_edge_ids and from_edge and not from_edge.startswith(":"):
            spatial_edge_ids.add(from_edge)

    target = str(profile.get("target") or "all")
    if target == "ride_hailing_in":
        match_mode = "destination"
    elif target == "ride_hailing_out":
        match_mode = "origin"
    else:
        match_mode = "route_contains"
    return {
        **profile,
        "spatial_edge_ids": sorted(spatial_edge_ids),
        "spatial_match_mode": match_mode,
        "matched_zone_ids": [str(zone.get("id")) for zone in matched_zones],
    }


if __name__ == "__main__":
    main()
