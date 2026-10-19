from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import copy
import xml.etree.ElementTree as ET
from pathlib import Path

from simtrend_app.closure_impact import analyze_closure_impact_root, resolve_incident_overlay_route
from simtrend_app.scenario_runtime import ScenarioRuntime, build_output_paths as runtime_output_paths


def save_json(path: str | Path, data: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def normalize_duration(duration_seconds: int | None) -> int:
    if duration_seconds is None or duration_seconds <= 0:
        return 300
    return min(duration_seconds, 3600)


DEFAULT_DEMAND_PROFILES = {
    "light": {
        "key": "light",
        "label": "轻流量",
        "multiplier": 0.61,
        "description": "约为标准需求的 61%。",
    },
    "standard": {
        "key": "standard",
        "label": "标准流量",
        "multiplier": 1.0,
        "description": "使用场景默认交通需求。",
    },
    "heavy": {
        "key": "heavy",
        "label": "高流量",
        "multiplier": 1.3,
        "description": "模拟交通负荷较高的拥堵风险场景。",
    },
    "peak": {
        "key": "peak",
        "label": "峰值流量",
        "multiplier": 1.6,
        "description": "模拟高峰或极端拥堵压力测试。",
    },
}


def infer_demand_profile(text: str) -> dict:
    custom_multiplier = re.search(r"自定义需求倍率：\s*(\d+(?:\.\d+)?)", text)
    custom_target = re.search(r"需求调整对象：\s*([a-z_]+)", text)
    if custom_multiplier and custom_target:
        multiplier = max(float(custom_multiplier.group(1)), 0.0)
        target = custom_target.group(1)
        target_labels = {
            "ride_hailing_in": "网约车到站流量",
            "ride_hailing_out": "网约车离站流量",
            "ride_hailing_all": "全部网约车流量",
            "background": "背景社会车辆流量",
            "all": "全部交通流量",
        }
        vehicle_multipliers = {}
        base_multiplier = multiplier if target == "all" else 1.0
        if target == "ride_hailing_all":
            vehicle_multipliers = {
                "ride_hailing_in": multiplier,
                "ride_hailing_out": multiplier,
            }
        elif target != "all":
            vehicle_multipliers[target] = multiplier
        return _with_demand_scope({
            "key": "custom",
            "label": f"{target_labels.get(target, target)} {multiplier:.2f} 倍",
            "multiplier": base_multiplier,
            "vehicle_multipliers": vehicle_multipliers,
            "description": "根据自然语言请求生成的自定义交通需求配置。",
            "target": target,
            "target_multiplier": multiplier,
        }, text)

    lowered = text.lower()
    mapping = [
        (("轻流量", "低流量", "低需求", "小流量", "light demand", "light traffic", "low demand"), "light"),
        (("标准流量", "正常流量", "默认流量", "标准需求", "standard demand", "normal traffic"), "standard"),
        (("高流量", "大流量", "高需求", "重流量", "heavy demand", "heavy traffic", "high demand"), "heavy"),
        (("早高峰", "晚高峰", "高峰", "峰值", "peak"), "peak"),
    ]
    for keywords, key in mapping:
        if any(keyword in text or keyword in lowered for keyword in keywords):
            return _with_demand_scope(dict(DEFAULT_DEMAND_PROFILES[key]), text)
    return _with_demand_scope(dict(DEFAULT_DEMAND_PROFILES["standard"]), text)


def _with_demand_scope(profile: dict, text: str) -> dict:
    scoped = dict(profile)
    time_match = re.search(r"需求调整时间窗：\s*(\d+)\s*-\s*(\d+)\s*秒", text)
    if time_match:
        scoped["time_window_start_s"] = int(time_match.group(1))
        scoped["time_window_end_s"] = int(time_match.group(2))
    spatial_match = re.search(r"需求调整空间范围：\s*([a-z0-9_#.-]+)", text, flags=re.I)
    spatial_label_match = re.search(r"需求调整空间名称：\s*([^\r\n]+)", text)
    if spatial_match:
        scoped["spatial_scope"] = spatial_match.group(1)
    if spatial_label_match:
        scoped["spatial_scope_label"] = spatial_label_match.group(1).strip()
    return scoped


def resolve_demand_profile(project_dir: Path, demand_profile: dict | None) -> dict:
    profile = dict(demand_profile or DEFAULT_DEMAND_PROFILES["standard"])
    key = str(profile.get("key") or "standard")
    scenario_file = project_dir / "scenario.json"
    if scenario_file.exists():
        try:
            payload = load_json(scenario_file)
            configured = (payload.get("demand_profiles") or {}).get(key)
            if configured:
                profile.update(configured)
        except (OSError, json.JSONDecodeError):
            pass
    profile["key"] = key
    profile["label"] = str(profile.get("label") or DEFAULT_DEMAND_PROFILES.get(key, DEFAULT_DEMAND_PROFILES["standard"])["label"])
    try:
        profile["multiplier"] = max(float(profile.get("multiplier", 1.0)), 0.05)
    except (TypeError, ValueError):
        profile["multiplier"] = 1.0
    profile["description"] = str(profile.get("description") or "")
    return profile


def ensure_project_files(project_dir: Path) -> None:
    ScenarioRuntime.from_project_dir(project_dir).validate_required_files()


def infer_target_plan(incident_text: str, scenario: str | None) -> dict:
    lowered = incident_text.lower()
    if "东进口" in incident_text or "east" in lowered:
        return _target_plan("east", "东进口", "east_west", "东西向", ["e2c_0"], ["flow_ew"])
    if "西进口" in incident_text or "west" in lowered:
        return _target_plan("west", "西进口", "east_west", "东西向", ["w2c_0"], ["flow_we"])
    if "北进口" in incident_text or "north" in lowered:
        return _target_plan("north", "北进口", "north_south", "南北向", ["n2c_0"], ["flow_ns"])
    if "南进口" in incident_text or "south" in lowered:
        return _target_plan("south", "南进口", "north_south", "南北向", ["s2c_0"], ["flow_sn"])
    if scenario and "corridor" in scenario.lower():
        return _target_plan(
            "east_west",
            "东西向走廊",
            "east_west",
            "东西向",
            ["e2c_0", "w2c_0"],
            ["flow_ew", "flow_we"],
        )
    return _target_plan(
        "east_west",
        "东西向走廊",
        "east_west",
        "东西向",
        ["e2c_0", "w2c_0"],
        ["flow_ew", "flow_we"],
    )


def _target_plan(
    target_key: str,
    target_label: str,
    axis_key: str,
    axis_label: str,
    lane_ids: list[str],
    route_prefixes: list[str],
) -> dict:
    return {
        "target_key": target_key,
        "target_label": target_label,
        "axis_key": axis_key,
        "axis_label": axis_label,
        "lane_ids": lane_ids,
        "route_prefixes": route_prefixes,
    }


def build_signal_plan(axis_key: str) -> dict:
    baseline = {"north_south_green_s": 42, "east_west_green_s": 42, "yellow_s": 3}
    if axis_key == "north_south":
        optimized = {"north_south_green_s": 60, "east_west_green_s": 24, "yellow_s": 3}
    else:
        optimized = {"north_south_green_s": 24, "east_west_green_s": 60, "yellow_s": 3}
    return {"baseline": baseline, "optimized": optimized}


def infer_incident_context(incident_text: str, target_plan: dict) -> dict:
    lowered = incident_text.lower()
    incident_type = None
    incident_type_label = None
    if any(word in incident_text or word in lowered for word in ["追尾", "rear-end"]):
        incident_type = "rear_end"
        incident_type_label = "追尾事故"
    elif any(word in incident_text or word in lowered for word in ["碰撞", "collision"]):
        incident_type = "collision"
        incident_type_label = "碰撞事故"
    elif any(word in incident_text or word in lowered for word in ["抛锚", "breakdown"]):
        incident_type = "breakdown"
        incident_type_label = "车辆故障"
    elif any(word in incident_text or word in lowered for word in ["拥堵", "排队", "queue", "congestion"]):
        incident_type = "congestion"
        incident_type_label = "拥堵/排队"

    duration_match = re.search(r"事故持续时间：\s*(\d{1,3})\s*分钟", incident_text)
    if not duration_match:
        duration_match = re.search(r"(?:持续|事故持续)\s*(\d{1,3})\s*分钟", incident_text)
    incident_duration_minutes = int(duration_match.group(1)) if duration_match else None

    closure_match = re.search(r"封闭车道数：\s*(\d+)", incident_text)
    if not closure_match:
        closure_match = re.search(r"封闭\s*(\d+)\s*条", incident_text)
    lane_closure_count = int(closure_match.group(1)) if closure_match else 0

    lane_id = target_plan["lane_ids"][0] if target_plan.get("lane_ids") else ""
    route_id = _incident_route_id_from_target(target_plan.get("target_key", ""))
    route_edges = _incident_route_edges(route_id)

    apply_scene_edit = bool(incident_type and lane_closure_count > 0 and incident_duration_minutes)
    return {
        "apply_scene_edit": apply_scene_edit,
        "incident_type": incident_type,
        "incident_type_label": incident_type_label,
        "incident_duration_minutes": incident_duration_minutes,
        "lane_closure_count": lane_closure_count,
        "blocked_lane_id": lane_id,
        "blocked_lane_label": target_plan.get("target_label"),
        "route_id": route_id,
        "route_edges": route_edges,
    }


def _incident_route_id_from_target(target_key: str) -> str:
    mapping = {
        "east": "ew",
        "west": "we",
        "north": "ns",
        "south": "sn",
        "east_west": "ew",
        "north_south": "ns",
    }
    return mapping.get(target_key, "ew")


def _incident_route_edges(route_id: str) -> str:
    mapping = {
        "ew": "e2c c2w",
        "we": "w2c c2e",
        "ns": "n2c c2s",
        "sn": "s2c c2n",
    }
    return mapping.get(route_id, "e2c c2w")


def prepare_run_root(project_dir: Path, *, reuse_latest: bool = False) -> Path:
    return ScenarioRuntime.from_project_dir(project_dir).create_run_root(reuse_latest=reuse_latest)


def build_output_paths(run_dir: Path) -> dict[str, Path]:
    return runtime_output_paths(run_dir)


def find_sumo_binary(name: str) -> str:
    sumo_home = os.environ.get("SUMO_HOME", "").strip()
    if not sumo_home:
        raise EnvironmentError("未检测到 SimTrend Engine 环境配置，请先安装仿真引擎并配置安装目录。")

    suffix = ".exe" if platform.system().lower().startswith("win") else ""
    candidate = Path(sumo_home) / "bin" / f"{name}{suffix}"
    if candidate.exists():
        return str(candidate)
    raise EnvironmentError("未找到 SimTrend Engine 可执行文件，请检查仿真引擎安装目录和环境配置。")


def run_command(label: str, command: list[str], workdir: Path, timeout_seconds: int) -> dict:
    try:
        completed = subprocess.run(
            command,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "label": label,
            "ok": completed.returncode == 0,
            "command": command,
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
            "returncode": completed.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "label": label,
            "ok": False,
            "command": command,
            "stdout": ((exc.stdout or "") if isinstance(exc.stdout, str) else "").strip(),
            "stderr": f"命令执行超时：超过 {timeout_seconds} 秒。",
            "returncode": -1,
        }


def run_simulation(
    label: str,
    sumo_binary: str,
    cfg_path: Path,
    workdir: Path,
    duration: int,
    outputs: dict[str, Path],
    random_seed: int | None = None,
) -> dict:
    # Reused debug directories must not expose artifacts from an earlier run.
    for output_path in outputs.values():
        output_path.unlink(missing_ok=True)

    command = [
        sumo_binary,
        "-c",
        str(cfg_path),
        "--tripinfo-output",
        str(outputs["tripinfo"]),
        "--tripinfo-output.write-unfinished",
        "true",
        "--queue-output",
        str(outputs["queue"]),
        "--statistic-output",
        str(outputs["statistics"]),
        "--summary-output",
        str(outputs["summary"]),
        "--fcd-output",
        str(outputs["fcd"]),
        "--device.fcd.probability",
        "1",
        "--device.fcd.period",
        "2",
        "--duration-log.statistics",
        "true",
        "--no-step-log",
        "true",
        "-e",
        str(duration),
    ]
    if random_seed is not None:
        command.extend(["--seed", str(int(random_seed))])
    return run_command(label=label, command=command, workdir=workdir, timeout_seconds=180)


def write_optimized_network(base_net_file: Path, optimized_net_file: Path, signal_plan: dict) -> None:
    tree = ET.parse(base_net_file)
    root = tree.getroot()
    phases = root.findall(".//tlLogic/phase")
    if len(phases) < 4:
        raise ValueError("未在路网文件中找到完整的信号相位定义。")

    optimized = signal_plan["optimized"]
    phases[0].set("duration", str(optimized["north_south_green_s"]))
    phases[2].set("duration", str(optimized["east_west_green_s"]))

    optimized_net_file.parent.mkdir(parents=True, exist_ok=True)
    tree.write(optimized_net_file, encoding="UTF-8", xml_declaration=True)


def write_sumocfg(
    cfg_path: Path,
    net_file: Path,
    route_files: Path | list[Path],
    duration: int,
    additional_files: Path | list[Path] | None = None,
) -> None:
    if isinstance(route_files, list):
        route_value = ",".join(str(path) for path in route_files)
    else:
        route_value = str(route_files)
    if isinstance(additional_files, list):
        additional_value = ",".join(str(path) for path in additional_files)
    elif additional_files:
        additional_value = str(additional_files)
    else:
        additional_value = ""
    input_lines = [
        "    <input>",
        f'        <net-file value="{net_file}"/>',
        f'        <route-files value="{route_value}"/>',
    ]
    if additional_value:
        input_lines.append(f'        <additional-files value="{additional_value}"/>')
    input_lines.append("    </input>")
    cfg_path.write_text(
        "\n".join(
            [
                "<configuration>",
                *input_lines,
                "    <time>",
                '        <begin value="0"/>',
                f'        <end value="{duration}"/>',
                "    </time>",
                "    <report>",
                '        <verbose value="false"/>',
                '        <no-step-log value="true"/>',
                "    </report>",
                "</configuration>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build_runtime_additional_files(
    output_dir: Path,
    incident_context: dict,
    duration_seconds: int,
    pickup_zones: list[dict] | None = None,
) -> list[Path]:
    additional_files: list[Path] = []

    if pickup_zones:
        pickup_file = output_dir / "pickup_zones.add.xml"
        write_pickup_zone_additional(pickup_file, pickup_zones)
        additional_files.append(pickup_file)

    if incident_context.get("apply_scene_edit"):
        additional_file = output_dir / "incident_closure.add.xml"
        write_incident_closure_additional(additional_file, incident_context, duration_seconds)
        additional_files.append(additional_file)

    return additional_files


def build_runtime_route_files(
    base_route_file: Path,
    output_dir: Path,
    incident_context: dict,
    duration_seconds: int,
) -> list[Path]:
    route_files = [base_route_file]
    if not incident_context.get("apply_scene_edit"):
        return route_files

    overlay_file = output_dir / "incident_overlay.rou.xml"
    write_incident_overlay_route(overlay_file, incident_context, duration_seconds)
    route_files.append(overlay_file)
    return route_files


def build_safe_runtime_route_plan(
    base_route_file: Path,
    net_file: Path,
    output_dir: Path,
    incident_context: dict,
    duration_seconds: int,
    pickup_zones: list[dict] | None = None,
    demand_profile: dict | None = None,
) -> dict:
    route_files = [base_route_file]
    pickup_zones = pickup_zones or []
    demand_profile = resolve_demand_profile(base_route_file.parents[1], demand_profile)
    impact = {
        "enabled": False,
        "blocked_edge_id": incident_context.get("blocked_edge_id", ""),
        "closed_lane_ids": incident_context.get("closed_lane_ids", []),
        "affected_route_ids": [],
        "affected_vehicle_ids": [],
        "removed_flow_ids": [],
        "delayed_flow_ids": [],
        "removed_vehicle_ids": [],
        "delayed_vehicle_ids": [],
        "closure_end_s": 0,
        "note": "",
    }
    pickup_waiting = _empty_pickup_waiting(pickup_zones)
    demand_adjustment = _empty_demand_adjustment(demand_profile)
    vehicle_multipliers = demand_profile.get("vehicle_multipliers") or {}
    demand_applies = (
        abs(float(demand_profile.get("multiplier", 1.0)) - 1.0) > 1e-6
        or any(abs(float(value) - 1.0) > 1e-6 for value in vehicle_multipliers.values())
    )
    if not incident_context.get("apply_scene_edit") and not pickup_zones and not demand_applies:
        return {
            "route_files": route_files,
            "incident_impact": impact,
            "pickup_waiting": pickup_waiting,
            "demand_adjustment": demand_adjustment,
        }

    runtime_route_file = output_dir / "runtime_routes.rou.xml"
    route_adjustment = write_safe_runtime_routes(
        base_route_file,
        net_file,
        runtime_route_file,
        incident_context,
        duration_seconds,
        pickup_zones=pickup_zones,
        demand_profile=demand_profile,
    )
    impact = route_adjustment["incident_impact"]
    pickup_waiting = route_adjustment["pickup_waiting"]
    demand_adjustment = route_adjustment["demand_adjustment"]
    route_files = [runtime_route_file]

    if incident_context.get("apply_scene_edit"):
        overlay_file = output_dir / "incident_overlay.rou.xml"
        write_incident_overlay_route(overlay_file, incident_context, duration_seconds)
        route_files.append(overlay_file)
    return {
        "route_files": route_files,
        "incident_impact": impact,
        "pickup_waiting": pickup_waiting,
        "demand_adjustment": demand_adjustment,
    }


def write_safe_runtime_routes(
    base_route_file: Path,
    net_file: Path,
    runtime_route_file: Path,
    incident_context: dict,
    duration_seconds: int,
    pickup_zones: list[dict] | None = None,
    demand_profile: dict | None = None,
) -> dict:
    tree = ET.parse(base_route_file)
    root = tree.getroot()
    pickup_zones = pickup_zones or []
    pickup_waiting = _empty_pickup_waiting(pickup_zones)
    demand_profile = demand_profile or DEFAULT_DEMAND_PROFILES["standard"]
    demand_adjustment = apply_demand_profile_to_routes(root, demand_profile)
    impact = analyze_closure_impact_root(
        root,
        net_file,
        incident_context,
        duration_seconds,
    )
    if not impact["enabled"]:
        pickup_waiting = apply_pickup_stops_to_routes(root, pickup_zones)
        runtime_route_file.parent.mkdir(parents=True, exist_ok=True)
        tree.write(runtime_route_file, encoding="UTF-8", xml_declaration=True)
        return {
            "incident_impact": impact,
            "pickup_waiting": pickup_waiting,
            "demand_adjustment": demand_adjustment,
        }

    closure_end_s = impact["closure_end_s"]
    affected_route_ids = impact["affected_route_ids"]
    affected_vehicle_ids = impact["affected_vehicle_ids"]
    removed_flow_ids: list[str] = []
    delayed_flow_ids: list[str] = []
    removed_vehicle_ids: list[str] = []
    delayed_vehicle_ids: list[str] = []
    if affected_route_ids:
        for flow in list(root.findall("flow")):
            if flow.get("route") not in affected_route_ids:
                continue
            flow_id = flow.get("id", "")
            begin = _parse_float(flow.get("begin"), 0.0)
            end = _parse_float(flow.get("end"), float(duration_seconds))
            if begin >= closure_end_s:
                continue
            if end <= closure_end_s or closure_end_s >= duration_seconds:
                root.remove(flow)
                removed_flow_ids.append(flow_id)
                continue
            flow.set("begin", _format_sumo_time(closure_end_s))
            delayed_flow_ids.append(flow_id)

    affected_vehicle_id_set = set(affected_vehicle_ids)
    for vehicle in list(root.findall("vehicle")):
        vehicle_id = vehicle.get("id", "")
        if vehicle_id not in affected_vehicle_id_set:
            continue
        depart = _parse_float(vehicle.get("depart"), 0.0)
        if depart >= closure_end_s:
            continue
        if closure_end_s >= duration_seconds:
            root.remove(vehicle)
            removed_vehicle_ids.append(vehicle_id)
            continue
        vehicle.set("depart", _format_sumo_time(closure_end_s))
        delayed_vehicle_ids.append(vehicle_id)

    if delayed_vehicle_ids or delayed_flow_ids:
        _sort_departing_elements(root)

    pickup_waiting = apply_pickup_stops_to_routes(root, pickup_zones)

    runtime_route_file.parent.mkdir(parents=True, exist_ok=True)
    tree.write(runtime_route_file, encoding="UTF-8", xml_declaration=True)

    impact = {
        **impact,
        "removed_flow_ids": removed_flow_ids,
        "delayed_flow_ids": delayed_flow_ids,
        "removed_vehicle_ids": removed_vehicle_ids,
        "delayed_vehicle_ids": delayed_vehicle_ids,
    }
    return {
        "incident_impact": impact,
        "pickup_waiting": pickup_waiting,
        "demand_adjustment": demand_adjustment,
    }


def apply_demand_profile_to_routes(routes_root: ET.Element, demand_profile: dict) -> dict:
    multiplier = float(demand_profile.get("multiplier", 1.0) or 1.0)
    scaled_flow_ids: list[str] = []
    original_flow_total = 0.0
    adjusted_flow_total = 0.0
    route_edges_by_id = {
        route.get("id", ""): (route.get("edges") or "").split()
        for route in routes_root.findall("route")
        if route.get("id")
    }
    flow_replacements: list[tuple[ET.Element, list[ET.Element]]] = []
    for flow in list(routes_root.findall("flow")):
        flow_id = flow.get("id", "")
        vehs_per_hour = _parse_float(flow.get("vehsPerHour"), 0.0)
        if vehs_per_hour <= 0:
            continue
        original_flow_total += vehs_per_hour
        time_start = demand_profile.get("time_window_start_s")
        time_end = demand_profile.get("time_window_end_s")
        applies = (
            abs(multiplier - 1.0) > 1e-6
            and _flow_matches_demand_scope(flow, demand_profile, route_edges_by_id)
            and _flow_overlaps_time_window(flow, time_start, time_end)
        )
        adjusted = max(vehs_per_hour * multiplier, 0.01) if applies else vehs_per_hour
        adjusted_flow_total += _equivalent_flow_rate(
            flow,
            vehs_per_hour,
            adjusted,
            time_start,
            time_end,
        )
        if not applies:
            continue
        if time_start is not None and time_end is not None:
            replacements = _split_flow_for_time_window(
                flow,
                float(time_start),
                float(time_end),
                adjusted,
            )
            if replacements:
                flow_replacements.append((flow, replacements))
        else:
            flow.set("vehsPerHour", _format_sumo_time(adjusted))
        if flow_id:
            scaled_flow_ids.append(flow_id)

    for original, replacements in flow_replacements:
        routes_root.remove(original)
        for replacement in replacements:
            routes_root.append(replacement)
    if flow_replacements:
        _sort_departing_elements(routes_root)

    vehicle_adjustment = _apply_vehicle_demand_profile(routes_root, demand_profile)
    enabled = bool(scaled_flow_ids) or vehicle_adjustment["vehicle_demand_enabled"]
    note_parts = []
    if scaled_flow_ids:
        note_parts.append(f"已按 {multiplier:.2f} 倍缩放 {len(scaled_flow_ids)} 条 flow 需求")
    if vehicle_adjustment["vehicle_demand_enabled"]:
        note_parts.append(
            f"已调整显式车辆 {vehicle_adjustment['original_vehicle_count']} -> "
            f"{vehicle_adjustment['adjusted_vehicle_count']} 辆"
        )

    return {
        "enabled": enabled,
        "profile_key": str(demand_profile.get("key", "standard")),
        "profile_label": str(demand_profile.get("label", "标准流量")),
        "multiplier": multiplier,
        "scaled_flow_ids": scaled_flow_ids,
        "scaled_flow_count": len(scaled_flow_ids),
        "original_total_vehs_per_hour": round(original_flow_total, 3),
        "adjusted_total_vehs_per_hour": round(adjusted_flow_total, 3),
        **vehicle_adjustment,
        "note": "；".join(note_parts) + "。" if note_parts else "当前使用场景默认需求，未额外缩放。",
    }


def _flow_matches_demand_scope(
    flow: ET.Element,
    demand_profile: dict,
    route_edges_by_id: dict[str, list[str]],
) -> bool:
    spatial_edge_ids = set(demand_profile.get("spatial_edge_ids") or [])
    if not spatial_edge_ids:
        return True
    edges = route_edges_by_id.get(flow.get("route", ""), [])
    if not edges:
        from_edge = flow.get("from")
        to_edge = flow.get("to")
        edges = [edge for edge in (from_edge, to_edge) if edge]
    if not edges:
        return False
    match_mode = demand_profile.get("spatial_match_mode") or "route_contains"
    if match_mode == "destination":
        return edges[-1] in spatial_edge_ids
    if match_mode == "origin":
        return edges[0] in spatial_edge_ids
    return any(edge_id in spatial_edge_ids for edge_id in edges)


def _flow_overlaps_time_window(flow: ET.Element, window_start: object, window_end: object) -> bool:
    if window_start is None or window_end is None:
        return True
    try:
        start = float(window_start)
        end = float(window_end)
    except (TypeError, ValueError):
        return True
    flow_begin = _parse_float(flow.get("begin"), 0.0)
    flow_end = _parse_float(flow.get("end"), end)
    return min(flow_end, end) > max(flow_begin, start)


def _equivalent_flow_rate(
    flow: ET.Element,
    original_rate: float,
    adjusted_rate: float,
    window_start: object,
    window_end: object,
) -> float:
    if window_start is None or window_end is None or adjusted_rate == original_rate:
        return adjusted_rate
    try:
        start = float(window_start)
        end = float(window_end)
    except (TypeError, ValueError):
        return adjusted_rate
    flow_begin = _parse_float(flow.get("begin"), 0.0)
    flow_end = _parse_float(flow.get("end"), end)
    duration = flow_end - flow_begin
    if duration <= 0:
        return original_rate
    overlap = max(min(flow_end, end) - max(flow_begin, start), 0.0)
    return original_rate + (adjusted_rate - original_rate) * overlap / duration


def _split_flow_for_time_window(
    flow: ET.Element,
    window_start: float,
    window_end: float,
    adjusted_rate: float,
) -> list[ET.Element]:
    flow_begin = _parse_float(flow.get("begin"), 0.0)
    flow_end = _parse_float(flow.get("end"), window_end)
    overlap_start = max(flow_begin, window_start)
    overlap_end = min(flow_end, window_end)
    if overlap_end <= overlap_start:
        return []
    flow_id = flow.get("id", "flow")
    segments = [
        (flow_begin, overlap_start, None, "before"),
        (overlap_start, overlap_end, adjusted_rate, "adjusted"),
        (overlap_end, flow_end, None, "after"),
    ]
    replacements = []
    for begin, end, rate, suffix in segments:
        if end <= begin:
            continue
        segment = copy.deepcopy(flow)
        segment.set("id", f"{flow_id}__{suffix}")
        segment.set("begin", _format_sumo_time(begin))
        segment.set("end", _format_sumo_time(end))
        if rate is not None:
            segment.set("vehsPerHour", _format_sumo_time(rate))
        replacements.append(segment)
    return replacements


def _apply_vehicle_demand_profile(routes_root: ET.Element, demand_profile: dict) -> dict:
    vehicles = list(routes_root.findall("vehicle"))
    if not vehicles:
        return _empty_vehicle_demand_adjustment()

    groups: dict[str, list[ET.Element]] = {}
    for vehicle in vehicles:
        groups.setdefault(_vehicle_demand_group(vehicle), []).append(vehicle)
    route_edges_by_id = {
        route.get("id", ""): (route.get("edges") or "").split()
        for route in routes_root.findall("route")
        if route.get("id")
    }

    removed_vehicle_ids: list[str] = []
    cloned_vehicle_ids: list[str] = []
    group_summaries: list[dict] = []
    for group_key, group_vehicles in groups.items():
        group_multiplier = _vehicle_group_multiplier(group_key, group_vehicles[0], demand_profile)
        original_count = len(group_vehicles)
        eligible_vehicles = [
            vehicle
            for vehicle in group_vehicles
            if _vehicle_matches_demand_scope(vehicle, demand_profile, route_edges_by_id)
        ]
        eligible_count = len(eligible_vehicles)
        target_eligible_count = max(int(round(eligible_count * group_multiplier)), 0)
        if target_eligible_count == eligible_count:
            group_summaries.append(
                _vehicle_group_summary(
                    group_key,
                    group_multiplier,
                    original_count,
                    original_count,
                    0,
                    0,
                    eligible_count=eligible_count,
                    adjusted_eligible_count=eligible_count,
                    demand_profile=demand_profile,
                )
            )
            continue
        if target_eligible_count < eligible_count:
            keep_indices = _evenly_spaced_indices(eligible_count, target_eligible_count)
            removed_count = 0
            for index, vehicle in enumerate(eligible_vehicles):
                if index in keep_indices:
                    continue
                vehicle_id = vehicle.get("id", "")
                routes_root.remove(vehicle)
                removed_count += 1
                if vehicle_id:
                    removed_vehicle_ids.append(vehicle_id)
            group_summaries.append(
                _vehicle_group_summary(
                    group_key,
                    group_multiplier,
                    original_count,
                    original_count - removed_count,
                    removed_count,
                    0,
                    eligible_count=eligible_count,
                    adjusted_eligible_count=target_eligible_count,
                    demand_profile=demand_profile,
                )
            )
            continue

        extra_count = target_eligible_count - eligible_count
        clones = _clone_extra_vehicles(
            eligible_vehicles,
            extra_count,
            time_window_end_s=demand_profile.get("time_window_end_s"),
        )
        for clone in clones:
            routes_root.append(clone)
            cloned_vehicle_ids.append(clone.get("id", ""))
        group_summaries.append(
            _vehicle_group_summary(
                group_key,
                group_multiplier,
                original_count,
                original_count + extra_count,
                0,
                extra_count,
                eligible_count=eligible_count,
                adjusted_eligible_count=target_eligible_count,
                demand_profile=demand_profile,
            )
        )

    if removed_vehicle_ids or cloned_vehicle_ids:
        _sort_departing_elements(routes_root)

    return {
        "vehicle_demand_enabled": bool(removed_vehicle_ids or cloned_vehicle_ids),
        "original_vehicle_count": len(vehicles),
        "adjusted_vehicle_count": len(routes_root.findall("vehicle")),
        "removed_vehicle_count": len(removed_vehicle_ids),
        "cloned_vehicle_count": len(cloned_vehicle_ids),
        "removed_vehicle_ids": removed_vehicle_ids,
        "cloned_vehicle_ids": cloned_vehicle_ids,
        "vehicle_group_summaries": group_summaries,
    }


def _empty_vehicle_demand_adjustment() -> dict:
    return {
        "vehicle_demand_enabled": False,
        "original_vehicle_count": 0,
        "adjusted_vehicle_count": 0,
        "removed_vehicle_count": 0,
        "cloned_vehicle_count": 0,
        "removed_vehicle_ids": [],
        "cloned_vehicle_ids": [],
        "vehicle_group_summaries": [],
    }


def _vehicle_demand_group(vehicle: ET.Element) -> str:
    vehicle_id = vehicle.get("id", "")
    if vehicle_id.startswith("rh_in_"):
        return "ride_hailing_in"
    if vehicle_id.startswith("rh_out_"):
        return "ride_hailing_out"
    if vehicle_id.startswith("bg_"):
        return "background"
    vehicle_type = vehicle.get("type", "")
    return vehicle_type or "other"


def _vehicle_group_multiplier(group_key: str, vehicle: ET.Element, demand_profile: dict) -> float:
    base_multiplier = float(demand_profile.get("multiplier", 1.0) or 1.0)
    vehicle_multipliers = demand_profile.get("vehicle_multipliers") or {}
    vehicle_type = vehicle.get("type", "")
    for key in (group_key, vehicle_type, "all"):
        if key in vehicle_multipliers:
            try:
                return max(float(vehicle_multipliers[key]), 0.0)
            except (TypeError, ValueError):
                return base_multiplier
    return base_multiplier


def _evenly_spaced_indices(total_count: int, target_count: int) -> set[int]:
    if target_count <= 0:
        return set()
    if target_count >= total_count:
        return set(range(total_count))
    if target_count == 1:
        return {0}
    return {
        round(index * (total_count - 1) / (target_count - 1))
        for index in range(target_count)
    }


def _clone_extra_vehicles(
    base_vehicles: list[ET.Element],
    extra_count: int,
    *,
    time_window_end_s: object = None,
) -> list[ET.Element]:
    clones: list[ET.Element] = []
    if not base_vehicles or extra_count <= 0:
        return clones
    base_count = len(base_vehicles)
    for extra_index in range(extra_count):
        source = base_vehicles[extra_index % base_count]
        clone = copy.deepcopy(source)
        cycle = extra_index // base_count + 1
        source_id = source.get("id", f"vehicle_{extra_index}")
        clone.set("id", f"{source_id}__demand_{cycle}_{extra_index}")
        depart = _parse_float(source.get("depart"), 0.0)
        clone_depart = depart + cycle * 5 + (extra_index % 5)
        try:
            if time_window_end_s is not None:
                clone_depart = min(clone_depart, max(float(time_window_end_s) - 0.001, 0.0))
        except (TypeError, ValueError):
            pass
        clone.set("depart", _format_sumo_time(clone_depart))
        clones.append(clone)
    return clones


def _vehicle_group_summary(
    group_key: str,
    multiplier: float,
    original_count: int,
    adjusted_count: int,
    removed_count: int,
    cloned_count: int,
    *,
    eligible_count: int | None = None,
    adjusted_eligible_count: int | None = None,
    demand_profile: dict | None = None,
) -> dict:
    profile = demand_profile or {}
    return {
        "group_key": group_key,
        "group_label": _vehicle_group_label(group_key),
        "multiplier": round(multiplier, 3),
        "original_count": original_count,
        "adjusted_count": adjusted_count,
        "removed_count": removed_count,
        "cloned_count": cloned_count,
        "eligible_count": original_count if eligible_count is None else eligible_count,
        "adjusted_eligible_count": adjusted_count if adjusted_eligible_count is None else adjusted_eligible_count,
        "time_window_start_s": profile.get("time_window_start_s"),
        "time_window_end_s": profile.get("time_window_end_s"),
        "spatial_scope": profile.get("spatial_scope"),
        "spatial_scope_label": profile.get("spatial_scope_label"),
    }


def _vehicle_matches_demand_scope(
    vehicle: ET.Element,
    demand_profile: dict,
    route_edges_by_id: dict[str, list[str]],
) -> bool:
    depart = _parse_float(vehicle.get("depart"), 0.0)
    start = demand_profile.get("time_window_start_s")
    end = demand_profile.get("time_window_end_s")
    try:
        if start is not None and depart < float(start):
            return False
        if end is not None and depart >= float(end):
            return False
    except (TypeError, ValueError):
        pass

    spatial_edge_ids = set(demand_profile.get("spatial_edge_ids") or [])
    if not spatial_edge_ids:
        return True
    inline_route = vehicle.find("route")
    edges = (
        (inline_route.get("edges") or "").split()
        if inline_route is not None
        else route_edges_by_id.get(vehicle.get("route", ""), [])
    )
    if not edges:
        return False
    match_mode = demand_profile.get("spatial_match_mode") or "route_contains"
    if match_mode == "destination":
        return edges[-1] in spatial_edge_ids
    if match_mode == "origin":
        return edges[0] in spatial_edge_ids
    return any(edge_id in spatial_edge_ids for edge_id in edges)


def _vehicle_group_label(group_key: str) -> str:
    labels = {
        "ride_hailing_in": "到站网约车",
        "ride_hailing_out": "离站网约车",
        "background": "背景交通",
        "ride_hailing": "网约车",
        "background_car": "背景交通",
    }
    return labels.get(group_key, group_key)


def load_pickup_zones(project_dir: Path) -> list[dict]:
    scenario_file = project_dir / "scenario.json"
    if not scenario_file.exists():
        return []
    try:
        payload = load_json(scenario_file)
    except (OSError, json.JSONDecodeError):
        return []
    zones = payload.get("map", {}).get("pickup_zones", [])
    normalized: list[dict] = []
    for zone in zones:
        if not isinstance(zone, dict) or zone.get("enabled", True) is False:
            continue
        lane_id = str(zone.get("lane_id") or "").strip()
        edge_id = str(zone.get("edge_id") or "").strip()
        if not edge_id and "_" in lane_id:
            edge_id = lane_id.rsplit("_", 1)[0]
        if not zone.get("id") or not lane_id or not edge_id:
            continue
        normalized.append(
            {
                **zone,
                "id": str(zone["id"]),
                "name": str(zone.get("name") or zone["id"]),
                "edge_id": edge_id,
                "lane_id": lane_id,
                "capacity": max(int(zone.get("capacity", 12) or 12), 1),
                "boarding_duration_s": max(int(zone.get("boarding_duration_s", 60) or 60), 1),
                "start_pos": max(float(zone.get("start_pos", 20) or 20), 0.0),
                "end_pos": max(float(zone.get("end_pos", 160) or 160), 1.0),
            }
        )
    return normalized


def write_pickup_zone_additional(additional_file: Path, pickup_zones: list[dict]) -> None:
    lines = ["<additional>"]
    for zone in pickup_zones:
        zone_id = _xml_escape(str(zone["id"]))
        lane_id = _xml_escape(str(zone["lane_id"]))
        capacity = max(int(zone.get("capacity", 12) or 12), 1)
        start_pos = _format_sumo_time(float(zone.get("start_pos", 20) or 20))
        end_pos = _format_sumo_time(float(zone.get("end_pos", 160) or 160))
        lines.append(
            f'    <parkingArea id="{zone_id}" lane="{lane_id}" startPos="{start_pos}" '
            f'endPos="{end_pos}" roadsideCapacity="{capacity}"/>'
        )
    lines.append("</additional>")
    additional_file.parent.mkdir(parents=True, exist_ok=True)
    additional_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_pickup_stops_to_routes(routes_root: ET.Element, pickup_zones: list[dict]) -> dict:
    if not pickup_zones:
        return _empty_pickup_waiting([])
    zone_stats = [
        {
            "id": str(zone["id"]),
            "name": str(zone.get("name") or zone["id"]),
            "edge_id": str(zone["edge_id"]),
            "lane_id": str(zone["lane_id"]),
            "capacity": max(int(zone.get("capacity", 12) or 12), 1),
            "boarding_duration_s": max(int(zone.get("boarding_duration_s", 60) or 60), 1),
            "matched_vehicle_count": 0,
            "stopped_vehicle_ids": [],
        }
        for zone in pickup_zones
    ]
    stats_by_id = {zone["id"]: zone for zone in zone_stats}
    route_edges_by_id = {
        route.get("id", ""): (route.get("edges") or "").split()
        for route in routes_root.findall("route")
        if route.get("id")
    }

    for vehicle in routes_root.findall("vehicle"):
        vehicle_id = vehicle.get("id", "")
        if not vehicle_id.startswith("rh_in_"):
            continue
        inline_route = vehicle.find("route")
        edges = (
            (inline_route.get("edges") or "").split()
            if inline_route is not None
            else route_edges_by_id.get(vehicle.get("route", ""), [])
        )
        if not edges:
            continue
        matched_zone = next((zone for zone in pickup_zones if str(zone["edge_id"]) in edges), None)
        if not matched_zone:
            continue
        if any(stop.get("parkingArea") == matched_zone["id"] for stop in vehicle.findall("stop")):
            continue
        stop = ET.Element(
            "stop",
            {
                "parkingArea": str(matched_zone["id"]),
                "duration": _format_sumo_time(max(int(matched_zone.get("boarding_duration_s", 60) or 60), 1)),
            },
        )
        if inline_route is not None:
            route_index = list(vehicle).index(inline_route)
            vehicle.insert(route_index + 1, stop)
        else:
            vehicle.append(stop)
        stats = stats_by_id[matched_zone["id"]]
        stats["matched_vehicle_count"] += 1
        stats["stopped_vehicle_ids"].append(vehicle_id)

    total_stopped = sum(zone["matched_vehicle_count"] for zone in zone_stats)
    return {
        "enabled": True,
        "zones": zone_stats,
        "total_stopped_vehicles": total_stopped,
        "note": f"已为 {total_stopped} 辆到达上客区的网约车插入停靠等待指令。",
    }


def _empty_pickup_waiting(pickup_zones: list[dict]) -> dict:
    return {
        "enabled": bool(pickup_zones),
        "zones": [
            {
                "id": str(zone.get("id", "")),
                "name": str(zone.get("name") or zone.get("id", "")),
                "edge_id": str(zone.get("edge_id", "")),
                "lane_id": str(zone.get("lane_id", "")),
                "capacity": max(int(zone.get("capacity", 12) or 12), 1),
                "boarding_duration_s": max(int(zone.get("boarding_duration_s", 60) or 60), 1),
                "matched_vehicle_count": 0,
                "stopped_vehicle_ids": [],
            }
            for zone in pickup_zones
        ],
        "total_stopped_vehicles": 0,
        "note": "",
    }


def _empty_demand_adjustment(demand_profile: dict) -> dict:
    multiplier = float(demand_profile.get("multiplier", 1.0) or 1.0)
    return {
        "enabled": abs(multiplier - 1.0) > 1e-6,
        "profile_key": str(demand_profile.get("key", "standard")),
        "profile_label": str(demand_profile.get("label", "标准流量")),
        "multiplier": multiplier,
        "scaled_flow_ids": [],
        "scaled_flow_count": 0,
        "original_total_vehs_per_hour": 0.0,
        "adjusted_total_vehs_per_hour": 0.0,
        "note": "",
    }


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _parse_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _format_sumo_time(value: float | int) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return str(round(numeric, 3))


def _sort_departing_elements(root: ET.Element) -> None:
    demand_tags = {"vehicle", "flow", "trip"}
    static_elements = [element for element in list(root) if element.tag not in demand_tags]
    demand_elements = [element for element in list(root) if element.tag in demand_tags]

    def departure_time(element: ET.Element) -> float:
        if element.tag == "flow":
            return _parse_float(element.get("begin"), 0.0)
        return _parse_float(element.get("depart"), 0.0)

    demand_elements.sort(key=lambda element: (departure_time(element), element.get("id", "")))
    root[:] = static_elements + demand_elements


def write_incident_overlay_route(
    overlay_file: Path,
    incident_context: dict,
    duration_seconds: int,
) -> None:
    duration = min(
        max(int(incident_context.get("incident_duration_minutes", 0) or 0) * 60, 60),
        duration_seconds,
    )
    route_id = incident_context.get("route_id", "ew")
    route_edges = resolve_incident_overlay_route(incident_context)
    lane_id = incident_context.get("blocked_lane_id", "e2c_0")
    depart_lane = lane_id.rsplit("_", 1)[1] if "_" in lane_id else "best"
    lane_pos = 5

    overlay_file.write_text(
        "\n".join(
            [
                "<routes>",
                '    <vType id="incident_blocker_type" accel="1.0" decel="4.5" sigma="0.0"'
                ' length="5" width="1.9" minGap="1.0" maxSpeed="0.1" vClass="authority"'
                ' guiShape="police" color="1.0,0.1,0.1"/>',
                f'    <route id="incident_{route_id}" edges="{route_edges}"/>',
                (
                    '    <vehicle id="incident_blocker" type="incident_blocker_type" '
                    f'route="incident_{route_id}" depart="0" departLane="{depart_lane}" '
                    f'departPos="{lane_pos}" departSpeed="0">'
                ),
                (
                    f'        <stop lane="{lane_id}" startPos="{lane_pos}" '
                    f'endPos="{lane_pos + 5}" duration="{duration}" parking="false" friendlyPos="true"/>'
                ),
                "    </vehicle>",
                "</routes>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_incident_closure_additional(
    additional_file: Path,
    incident_context: dict,
    duration_seconds: int,
) -> None:
    duration = min(
        max(int(incident_context.get("incident_duration_minutes", 0) or 0) * 60, 60),
        duration_seconds,
    )
    closed_lane_ids = incident_context.get("closed_lane_ids") or [incident_context.get("blocked_lane_id", "e2c_0")]
    blocked_edge_id = incident_context.get("blocked_edge_id")
    if not blocked_edge_id:
        blocked_lane_id = incident_context.get("blocked_lane_id", "e2c_0")
        blocked_edge_id = blocked_lane_id.rsplit("_", 1)[0]

    lines = [
        "<additional>",
        f'    <rerouter id="incident_lane_closure" edges="{blocked_edge_id}">',
        f'        <interval begin="0" end="{duration}">',
    ]
    for lane_id in closed_lane_ids:
        lines.append(f'            <closingLaneReroute id="{lane_id}" allow="authority"/>')
    lines.extend(
        [
            "        </interval>",
            "    </rerouter>",
            "</additional>",
            "",
        ]
    )
    additional_file.write_text("\n".join(lines), encoding="utf-8")


def load_xml_root(path: str | Path) -> ET.Element:
    text = Path(path).read_text(encoding="utf-8")
    cleaned = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return ET.fromstring(cleaned)


def collect_metrics(outputs: dict[str, str], target_plan: dict) -> dict[str, float]:
    stats_root = load_xml_root(outputs["statistics"])
    summary_root = load_xml_root(outputs["summary"])
    tripinfo_root = load_xml_root(outputs["tripinfo"])
    queue_root = load_xml_root(outputs["queue"])

    vehicle_trip_stats = stats_root.find("vehicleTripStatistics")
    vehicles_node = stats_root.find("vehicles")
    steps = summary_root.findall("step")

    overall_avg_wait_s = to_float(vehicle_trip_stats, "waitingTime")
    overall_time_loss_s = to_float(vehicle_trip_stats, "timeLoss")
    completed_trip_count = to_float(vehicle_trip_stats, "count")
    inserted_vehicle_count = to_float(vehicles_node, "inserted")
    running_vehicle_count = to_float(vehicles_node, "running")
    # SUMO summary counters are cumulative; the final step is the simulation total.
    arrived_vehicle_count = to_float(steps[-1], "arrived") if steps else 0.0
    max_halting_vehicles = max((to_float(step, "halting") for step in steps), default=0.0)

    target_avg_queue_m, target_max_queue_m = collect_queue_metrics(queue_root, target_plan["lane_ids"])
    target_avg_wait_s, target_avg_time_loss_s, target_avg_duration_s, target_trip_count = collect_trip_metrics(
        tripinfo_root,
        target_plan["route_prefixes"],
    )

    return {
        "overall_avg_wait_s": round(overall_avg_wait_s, 2),
        "overall_time_loss_s": round(overall_time_loss_s, 2),
        "completed_trip_count": round(completed_trip_count, 2),
        "inserted_vehicle_count": round(inserted_vehicle_count, 2),
        "running_vehicle_count": round(running_vehicle_count, 2),
        "arrived_vehicle_count": round(arrived_vehicle_count, 2),
        "max_halting_vehicles": round(max_halting_vehicles, 2),
        "target_avg_queue_m": round(target_avg_queue_m, 2),
        "target_max_queue_m": round(target_max_queue_m, 2),
        "target_avg_wait_s": round(target_avg_wait_s, 2),
        "target_avg_time_loss_s": round(target_avg_time_loss_s, 2),
        "target_avg_duration_s": round(target_avg_duration_s, 2),
        "target_trip_count": round(target_trip_count, 2),
    }


def build_comparison(baseline: dict[str, float], optimized: dict[str, float]) -> dict[str, float]:
    return {
        "target_avg_queue_before_m": baseline["target_avg_queue_m"],
        "target_avg_queue_after_m": optimized["target_avg_queue_m"],
        "target_avg_queue_delta_m": round(optimized["target_avg_queue_m"] - baseline["target_avg_queue_m"], 2),
        "target_max_queue_before_m": baseline["target_max_queue_m"],
        "target_max_queue_after_m": optimized["target_max_queue_m"],
        "target_max_queue_delta_m": round(optimized["target_max_queue_m"] - baseline["target_max_queue_m"], 2),
        "target_avg_wait_before_s": baseline["target_avg_wait_s"],
        "target_avg_wait_after_s": optimized["target_avg_wait_s"],
        "target_avg_wait_delta_s": round(optimized["target_avg_wait_s"] - baseline["target_avg_wait_s"], 2),
        "overall_avg_wait_before_s": baseline["overall_avg_wait_s"],
        "overall_avg_wait_after_s": optimized["overall_avg_wait_s"],
        "overall_avg_wait_delta_s": round(optimized["overall_avg_wait_s"] - baseline["overall_avg_wait_s"], 2),
        "arrived_before": baseline["arrived_vehicle_count"],
        "arrived_after": optimized["arrived_vehicle_count"],
        "arrived_delta": round(optimized["arrived_vehicle_count"] - baseline["arrived_vehicle_count"], 2),
        "max_halting_before": baseline["max_halting_vehicles"],
        "max_halting_after": optimized["max_halting_vehicles"],
        "max_halting_delta": round(optimized["max_halting_vehicles"] - baseline["max_halting_vehicles"], 2),
    }


def build_tradeoff_note(comparison: dict[str, float], target_plan: dict) -> str:
    target_improved = comparison["target_avg_queue_delta_m"] < 0 and comparison["target_avg_wait_delta_s"] < 0
    global_worsened = (
        comparison["overall_avg_wait_delta_s"] > 0
        or comparison["arrived_delta"] < 0
        or comparison["max_halting_delta"] > 0
    )
    if target_improved and global_worsened:
        return (
            f"优化方案显著缓解了{target_plan['target_label']}的排队与等待，"
            "但全路口整体效率出现一定回落，属于典型的事故方向优先控制策略。"
        )
    if target_improved:
        return f"优化方案同时改善了{target_plan['target_label']}与全局指标，可以作为优先候选方案。"
    return f"当前配时调整没有明显改善{target_plan['target_label']}指标，建议继续搜索更合适的相位方案。"


def format_comparison_summary(comparison: dict[str, float], signal_plan: dict) -> str:
    baseline_plan = signal_plan["baseline"]
    optimized_plan = signal_plan["optimized"]
    return "\n".join(
        [
            "对比指标摘要：",
            (
                f"- 信号配时：NS {baseline_plan['north_south_green_s']}s / EW {baseline_plan['east_west_green_s']}s"
                f" -> NS {optimized_plan['north_south_green_s']}s / EW {optimized_plan['east_west_green_s']}s"
            ),
            (
                f"- 目标车道平均排队长度：{comparison['target_avg_queue_before_m']:.2f} m"
                f" -> {comparison['target_avg_queue_after_m']:.2f} m"
                f"（变化 {comparison['target_avg_queue_delta_m']:+.2f} m）"
            ),
            (
                f"- 目标车流平均等待时间：{comparison['target_avg_wait_before_s']:.2f} s"
                f" -> {comparison['target_avg_wait_after_s']:.2f} s"
                f"（变化 {comparison['target_avg_wait_delta_s']:+.2f} s）"
            ),
            (
                f"- 全局平均等待：{comparison['overall_avg_wait_before_s']:.2f} s"
                f" -> {comparison['overall_avg_wait_after_s']:.2f} s"
                f"（变化 {comparison['overall_avg_wait_delta_s']:+.2f} s）"
            ),
            (
                f"- 全路网完成车辆数：{comparison['arrived_before']:.0f}"
                f" -> {comparison['arrived_after']:.0f}"
                f"（变化 {comparison['arrived_delta']:+.0f}）"
            ),
        ]
    )


def format_runs(runs: list[dict]) -> str:
    if not runs:
        return "本次没有执行任何命令。"

    parts: list[str] = []
    for index, run in enumerate(runs, start=1):
        status = "成功" if run.get("ok") else "失败"
        command_text = _sanitize_demo_text(" ".join(run.get("command", [])))
        stdout_text = _sanitize_demo_text(clip_text(str(run.get("stdout", ""))))
        stderr_text = _sanitize_demo_text(clip_text(str(run.get("stderr", ""))))
        parts.append(
            "\n".join(
                [
                    f"{index}. {run.get('label', '命令')}：{status}",
                    f"命令：{command_text}",
                    f"返回码：{run.get('returncode')}",
                    f"stdout：{stdout_text}",
                    f"stderr：{stderr_text}",
                ]
            )
        )
    return "\n\n".join(parts)


def _sanitize_demo_text(value: str) -> str:
    sanitized = value.replace("SUMO_HOME", "SIMTREND_ENGINE_HOME")
    sanitized = re.sub(r"(?i)sumo(?:\\.exe)?", "SimTrend Engine", sanitized)
    sanitized = sanitized.replace("sumo_min_rl_skeleton", "SimTrend_min_rl_skeleton")
    return sanitized


def clip_text(value: str, limit: int = 300) -> str:
    if not value:
        return "无"
    if len(value) <= limit:
        return value
    return value[:limit] + "...(已截断)"


def to_float(node: ET.Element | None, attribute: str) -> float:
    if node is None:
        return 0.0
    value = node.get(attribute)
    try:
        return float(value) if value is not None else 0.0
    except ValueError:
        return 0.0


def collect_queue_metrics(queue_root: ET.Element, lane_ids: list[str]) -> tuple[float, float]:
    values: list[float] = []
    for lane_id in lane_ids:
        for lane in queue_root.findall(f".//lane[@id='{lane_id}']"):
            values.append(to_float(lane, "queueing_length"))
    if not values:
        return 0.0, 0.0
    return sum(values) / len(values), max(values)


def collect_trip_metrics(tripinfo_root: ET.Element, route_prefixes: list[str]) -> tuple[float, float, float, float]:
    trips = [
        trip
        for trip in tripinfo_root.findall("tripinfo")
        if any(trip.get("id", "").startswith(prefix) for prefix in route_prefixes)
    ]
    if not trips:
        return 0.0, 0.0, 0.0, 0.0
    avg_wait = sum(to_float(trip, "waitingTime") for trip in trips) / len(trips)
    avg_time_loss = sum(to_float(trip, "timeLoss") for trip in trips) / len(trips)
    avg_duration = sum(to_float(trip, "duration") for trip in trips) / len(trips)
    return avg_wait, avg_time_loss, avg_duration, float(len(trips))


def infer_target_plan(incident_text: str, scenario: str | None) -> dict:
    lowered = incident_text.lower()
    east_lanes = ["e0_c10_0", "e0_c10_1", "e0_c10_2", "e1_c11_0", "e1_c11_1", "e1_c11_2"]
    west_lanes = ["w0_c00_0", "w0_c00_1", "w0_c00_2", "w1_c01_0", "w1_c01_1", "w1_c01_2"]
    north_lanes = ["n0_c00_0", "n0_c00_1", "n0_c00_2", "n1_c10_0", "n1_c10_1", "n1_c10_2"]
    south_lanes = ["s0_c01_0", "s0_c01_1", "s0_c01_2", "s1_c11_0", "s1_c11_1", "s1_c11_2"]

    if "东进口" in incident_text or "east" in lowered:
        return _target_plan("east", "东侧进口群", "east_west", "东西向", east_lanes, ["flow_e0_", "flow_e1_"])
    if "西进口" in incident_text or "west" in lowered:
        return _target_plan("west", "西侧进口群", "east_west", "东西向", west_lanes, ["flow_w0_", "flow_w1_"])
    if "北进口" in incident_text or "north" in lowered:
        return _target_plan("north", "北侧进口群", "north_south", "南北向", north_lanes, ["flow_n0_", "flow_n1_"])
    if "南进口" in incident_text or "south" in lowered:
        return _target_plan("south", "南侧进口群", "north_south", "南北向", south_lanes, ["flow_s0_", "flow_s1_"])
    if scenario and "corridor" in scenario.lower():
        return _target_plan(
            "east_west",
            "东西向走廊",
            "east_west",
            "东西向",
            west_lanes + east_lanes,
            ["flow_w0_", "flow_w1_", "flow_e0_", "flow_e1_"],
        )
    return _target_plan(
        "east_west",
        "东西向走廊",
        "east_west",
        "东西向",
        west_lanes + east_lanes,
        ["flow_w0_", "flow_w1_", "flow_e0_", "flow_e1_"],
    )


def _incident_route_id_from_target(target_key: str) -> str:
    mapping = {
        "east": "east_top",
        "west": "west_top",
        "north": "north_left",
        "south": "south_left",
        "east_west": "east_top",
        "north_south": "north_left",
    }
    return mapping.get(target_key, "east_top")


def _incident_route_edges(route_id: str) -> str:
    mapping = {
        "east_top": "e0_c10 c10_c00",
        "west_top": "w0_c00 c00_c10",
        "north_left": "n0_c00 c00_c01",
        "south_left": "s0_c01 c01_c00",
    }
    return mapping.get(route_id, "e0_c10 c10_c00")


def write_optimized_network(base_net_file: Path, optimized_net_file: Path, signal_plan: dict) -> None:
    tree = ET.parse(base_net_file)
    root = tree.getroot()
    optimized = signal_plan["optimized"]

    tl_logics = root.findall(".//tlLogic")
    if not tl_logics:
        raise ValueError("未在路网文件中找到信号控制定义。")

    updated = 0
    for tl_logic in tl_logics:
        phases = tl_logic.findall("phase")
        if len(phases) < 3:
            continue
        phases[0].set("duration", str(optimized["north_south_green_s"]))
        phases[2].set("duration", str(optimized["east_west_green_s"]))
        updated += 1

    if updated == 0:
        raise ValueError("未找到可更新的信号相位定义。")

    optimized_net_file.parent.mkdir(parents=True, exist_ok=True)
    tree.write(optimized_net_file, encoding="UTF-8", xml_declaration=True)


_PRECISE_APPROACH_MAP = {
    ("\u897f\u5317\u8def\u53e3", "\u5317\u8fdb\u53e3"): {
        "target_key": "c00_north",
        "target_label": "\u897f\u5317\u8def\u53e3\u5317\u8fdb\u53e3",
        "axis_key": "north_south",
        "axis_label": "\u5357\u5317\u5411",
        "lane_ids": ["n0_c00_0", "n0_c00_1", "n0_c00_2"],
        "route_prefixes": ["flow_n0_"],
        "blocked_lane_id": "n0_c00_0",
        "route_edges": "n0_c00 c00_c01",
    },
    ("\u897f\u5317\u8def\u53e3", "\u5357\u8fdb\u53e3"): {
        "target_key": "c00_south",
        "target_label": "\u897f\u5317\u8def\u53e3\u5357\u8fdb\u53e3",
        "axis_key": "north_south",
        "axis_label": "\u5357\u5317\u5411",
        "lane_ids": ["c01_c00_0", "c01_c00_1", "c01_c00_2"],
        "route_prefixes": ["flow_s0_through", "flow_w1_left"],
        "blocked_lane_id": "c01_c00_0",
        "route_edges": "c01_c00 c00_n0",
    },
    ("\u897f\u5317\u8def\u53e3", "\u897f\u8fdb\u53e3"): {
        "target_key": "c00_west",
        "target_label": "\u897f\u5317\u8def\u53e3\u897f\u8fdb\u53e3",
        "axis_key": "east_west",
        "axis_label": "\u4e1c\u897f\u5411",
        "lane_ids": ["w0_c00_0", "w0_c00_1", "w0_c00_2"],
        "route_prefixes": ["flow_w0_"],
        "blocked_lane_id": "w0_c00_0",
        "route_edges": "w0_c00 c00_c10",
    },
    ("\u897f\u5317\u8def\u53e3", "\u4e1c\u8fdb\u53e3"): {
        "target_key": "c00_east",
        "target_label": "\u897f\u5317\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "axis_key": "east_west",
        "axis_label": "\u4e1c\u897f\u5411",
        "lane_ids": ["c10_c00_0", "c10_c00_1", "c10_c00_2"],
        "route_prefixes": ["flow_n1_right", "flow_e0_through"],
        "blocked_lane_id": "c10_c00_0",
        "route_edges": "c10_c00 c00_w0",
    },
    ("\u4e1c\u5317\u8def\u53e3", "\u5317\u8fdb\u53e3"): {
        "target_key": "c10_north",
        "target_label": "\u4e1c\u5317\u8def\u53e3\u5317\u8fdb\u53e3",
        "axis_key": "north_south",
        "axis_label": "\u5357\u5317\u5411",
        "lane_ids": ["n1_c10_0", "n1_c10_1", "n1_c10_2"],
        "route_prefixes": ["flow_n1_"],
        "blocked_lane_id": "n1_c10_0",
        "route_edges": "n1_c10 c10_c11",
    },
    ("\u4e1c\u5317\u8def\u53e3", "\u5357\u8fdb\u53e3"): {
        "target_key": "c10_south",
        "target_label": "\u4e1c\u5317\u8def\u53e3\u5357\u8fdb\u53e3",
        "axis_key": "north_south",
        "axis_label": "\u5357\u5317\u5411",
        "lane_ids": ["c11_c10_0", "c11_c10_1", "c11_c10_2"],
        "route_prefixes": ["flow_s1_through", "flow_e1_right"],
        "blocked_lane_id": "c11_c10_0",
        "route_edges": "c11_c10 c10_n1",
    },
    ("\u4e1c\u5317\u8def\u53e3", "\u897f\u8fdb\u53e3"): {
        "target_key": "c10_west",
        "target_label": "\u4e1c\u5317\u8def\u53e3\u897f\u8fdb\u53e3",
        "axis_key": "east_west",
        "axis_label": "\u4e1c\u897f\u5411",
        "lane_ids": ["c00_c10_0", "c00_c10_1", "c00_c10_2"],
        "route_prefixes": ["flow_n0_left", "flow_w0_through"],
        "blocked_lane_id": "c00_c10_0",
        "route_edges": "c00_c10 c10_e0",
    },
    ("\u4e1c\u5317\u8def\u53e3", "\u4e1c\u8fdb\u53e3"): {
        "target_key": "c10_east",
        "target_label": "\u4e1c\u5317\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "axis_key": "east_west",
        "axis_label": "\u4e1c\u897f\u5411",
        "lane_ids": ["e0_c10_0", "e0_c10_1", "e0_c10_2"],
        "route_prefixes": ["flow_e0_"],
        "blocked_lane_id": "e0_c10_0",
        "route_edges": "e0_c10 c10_c00",
    },
    ("\u897f\u5357\u8def\u53e3", "\u5317\u8fdb\u53e3"): {
        "target_key": "c01_north",
        "target_label": "\u897f\u5357\u8def\u53e3\u5317\u8fdb\u53e3",
        "axis_key": "north_south",
        "axis_label": "\u5357\u5317\u5411",
        "lane_ids": ["c00_c01_0", "c00_c01_1", "c00_c01_2"],
        "route_prefixes": ["flow_n0_through", "flow_w0_right"],
        "blocked_lane_id": "c00_c01_0",
        "route_edges": "c00_c01 c01_s0",
    },
    ("\u897f\u5357\u8def\u53e3", "\u5357\u8fdb\u53e3"): {
        "target_key": "c01_south",
        "target_label": "\u897f\u5357\u8def\u53e3\u5357\u8fdb\u53e3",
        "axis_key": "north_south",
        "axis_label": "\u5357\u5317\u5411",
        "lane_ids": ["s0_c01_0", "s0_c01_1", "s0_c01_2"],
        "route_prefixes": ["flow_s0_"],
        "blocked_lane_id": "s0_c01_0",
        "route_edges": "s0_c01 c01_c00",
    },
    ("\u897f\u5357\u8def\u53e3", "\u897f\u8fdb\u53e3"): {
        "target_key": "c01_west",
        "target_label": "\u897f\u5357\u8def\u53e3\u897f\u8fdb\u53e3",
        "axis_key": "east_west",
        "axis_label": "\u4e1c\u897f\u5411",
        "lane_ids": ["w1_c01_0", "w1_c01_1", "w1_c01_2"],
        "route_prefixes": ["flow_w1_"],
        "blocked_lane_id": "w1_c01_0",
        "route_edges": "w1_c01 c01_c11",
    },
    ("\u897f\u5357\u8def\u53e3", "\u4e1c\u8fdb\u53e3"): {
        "target_key": "c01_east",
        "target_label": "\u897f\u5357\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "axis_key": "east_west",
        "axis_label": "\u4e1c\u897f\u5411",
        "lane_ids": ["c11_c01_0", "c11_c01_1", "c11_c01_2"],
        "route_prefixes": ["flow_s1_left", "flow_e1_through"],
        "blocked_lane_id": "c11_c01_0",
        "route_edges": "c11_c01 c01_w1",
    },
    ("\u4e1c\u5357\u8def\u53e3", "\u5317\u8fdb\u53e3"): {
        "target_key": "c11_north",
        "target_label": "\u4e1c\u5357\u8def\u53e3\u5317\u8fdb\u53e3",
        "axis_key": "north_south",
        "axis_label": "\u5357\u5317\u5411",
        "lane_ids": ["c10_c11_0", "c10_c11_1", "c10_c11_2"],
        "route_prefixes": ["flow_n1_through", "flow_e0_left"],
        "blocked_lane_id": "c10_c11_0",
        "route_edges": "c10_c11 c11_s1",
    },
    ("\u4e1c\u5357\u8def\u53e3", "\u5357\u8fdb\u53e3"): {
        "target_key": "c11_south",
        "target_label": "\u4e1c\u5357\u8def\u53e3\u5357\u8fdb\u53e3",
        "axis_key": "north_south",
        "axis_label": "\u5357\u5317\u5411",
        "lane_ids": ["s1_c11_0", "s1_c11_1", "s1_c11_2"],
        "route_prefixes": ["flow_s1_"],
        "blocked_lane_id": "s1_c11_0",
        "route_edges": "s1_c11 c11_c10",
    },
    ("\u4e1c\u5357\u8def\u53e3", "\u897f\u8fdb\u53e3"): {
        "target_key": "c11_west",
        "target_label": "\u4e1c\u5357\u8def\u53e3\u897f\u8fdb\u53e3",
        "axis_key": "east_west",
        "axis_label": "\u4e1c\u897f\u5411",
        "lane_ids": ["c01_c11_0", "c01_c11_1", "c01_c11_2"],
        "route_prefixes": ["flow_s0_right", "flow_w1_through"],
        "blocked_lane_id": "c01_c11_0",
        "route_edges": "c01_c11 c11_e1",
    },
    ("\u4e1c\u5357\u8def\u53e3", "\u4e1c\u8fdb\u53e3"): {
        "target_key": "c11_east",
        "target_label": "\u4e1c\u5357\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "axis_key": "east_west",
        "axis_label": "\u4e1c\u897f\u5411",
        "lane_ids": ["e1_c11_0", "e1_c11_1", "e1_c11_2"],
        "route_prefixes": ["flow_e1_"],
        "blocked_lane_id": "e1_c11_0",
        "route_edges": "e1_c11 c11_c01",
    },
}


def infer_target_plan(incident_text: str, scenario: str | None) -> dict:
    scenario_text = (scenario or "").lower()
    map_plan = _target_plan_from_map_context(incident_text, scenario_text)
    if map_plan:
        return map_plan

    if "nanjing_south" in scenario_text or "ride_hailing" in scenario_text or "南京南站" in incident_text:
        return _target_plan(
            "nanjing_south_station",
            "南京南站网约车上客区",
            "station_circulation",
            "站区集散交通",
            [],
            ["rh_"],
        )

    for (junction_label, approach_label), payload in _PRECISE_APPROACH_MAP.items():
        if junction_label in incident_text and approach_label in incident_text:
            return _target_plan(
                payload["target_key"],
                payload["target_label"],
                payload["axis_key"],
                payload["axis_label"],
                payload["lane_ids"],
                payload["route_prefixes"],
            )

    lowered = incident_text.lower()
    east_lanes = ["e0_c10_0", "e0_c10_1", "e0_c10_2", "e1_c11_0", "e1_c11_1", "e1_c11_2"]
    west_lanes = ["w0_c00_0", "w0_c00_1", "w0_c00_2", "w1_c01_0", "w1_c01_1", "w1_c01_2"]
    north_lanes = ["n0_c00_0", "n0_c00_1", "n0_c00_2", "n1_c10_0", "n1_c10_1", "n1_c10_2"]
    south_lanes = ["s0_c01_0", "s0_c01_1", "s0_c01_2", "s1_c11_0", "s1_c11_1", "s1_c11_2"]

    if "\u4e1c\u8fdb\u53e3" in incident_text or "east" in lowered:
        return _target_plan("east", "\u4e1c\u4fa7\u8fdb\u53e3\u7fa4", "east_west", "\u4e1c\u897f\u5411", east_lanes, ["flow_e0_", "flow_e1_"])
    if "\u897f\u8fdb\u53e3" in incident_text or "west" in lowered:
        return _target_plan("west", "\u897f\u4fa7\u8fdb\u53e3\u7fa4", "east_west", "\u4e1c\u897f\u5411", west_lanes, ["flow_w0_", "flow_w1_"])
    if "\u5317\u8fdb\u53e3" in incident_text or "north" in lowered:
        return _target_plan("north", "\u5317\u4fa7\u8fdb\u53e3\u7fa4", "north_south", "\u5357\u5317\u5411", north_lanes, ["flow_n0_", "flow_n1_"])
    if "\u5357\u8fdb\u53e3" in incident_text or "south" in lowered:
        return _target_plan("south", "\u5357\u4fa7\u8fdb\u53e3\u7fa4", "north_south", "\u5357\u5317\u5411", south_lanes, ["flow_s0_", "flow_s1_"])
    return _target_plan(
        "east_west",
        "\u4e1c\u897f\u5411\u8d70\u5eca",
        "east_west",
        "\u4e1c\u897f\u5411",
        west_lanes + east_lanes,
        ["flow_w0_", "flow_w1_", "flow_e0_", "flow_e1_"],
    )


def infer_incident_context(incident_text: str, target_plan: dict) -> dict:
    lowered = incident_text.lower()
    incident_type = None
    incident_type_label = None
    if any(word in incident_text or word in lowered for word in ["\u8ffd\u5c3e", "rear-end"]):
        incident_type = "rear_end"
        incident_type_label = "\u8ffd\u5c3e\u4e8b\u6545"
    elif any(word in incident_text or word in lowered for word in ["\u78b0\u649e", "collision"]):
        incident_type = "collision"
        incident_type_label = "\u78b0\u649e\u4e8b\u6545"
    elif any(word in incident_text or word in lowered for word in ["\u629b\u951a", "breakdown"]):
        incident_type = "breakdown"
        incident_type_label = "\u8f66\u8f86\u6545\u969c"
    elif any(word in incident_text or word in lowered for word in ["\u62e5\u5835", "\u6392\u961f", "queue", "congestion"]):
        incident_type = "congestion"
        incident_type_label = "\u62e5\u5835/\u6392\u961f"

    duration_match = re.search(r"(?:\u6301\u7eed|\u4e8b\u6545\u6301\u7eed)\s*(\d{1,3})\s*\u5206\u949f", incident_text)
    incident_duration_minutes = int(duration_match.group(1)) if duration_match else None

    closure_match = re.search(r"\u5c01\u95ed\s*(\d+)\s*\u6761", incident_text)
    lane_closure_count = int(closure_match.group(1)) if closure_match else 0

    blocked_lane_id = target_plan["lane_ids"][0] if target_plan.get("lane_ids") else ""
    route_edges = None
    for payload in _PRECISE_APPROACH_MAP.values():
        if payload["target_key"] == target_plan.get("target_key"):
            route_edges = payload["route_edges"]
            blocked_lane_id = payload["blocked_lane_id"]
            break
    if route_edges is None:
        route_edges = "e0_c10 c10_c00"

    apply_scene_edit = bool(incident_type and lane_closure_count > 0 and incident_duration_minutes)
    return {
        "apply_scene_edit": apply_scene_edit,
        "incident_type": incident_type,
        "incident_type_label": incident_type_label,
        "incident_duration_minutes": incident_duration_minutes,
        "lane_closure_count": lane_closure_count,
        "blocked_lane_id": blocked_lane_id,
        "blocked_lane_label": target_plan.get("target_label"),
        "route_id": target_plan.get("target_key", "incident_route"),
        "route_edges": route_edges,
    }


_TURN_KEYWORDS = {
    "left": ["左转车道", "左转道", "左转"],
    "through": ["直行车道", "直行道", "直行"],
    "right": ["右转车道", "右转道", "右转"],
}
_TURN_LABELS = {
    "left": "\u5de6\u8f6c\u8f66\u9053",
    "through": "\u76f4\u884c\u8f66\u9053",
    "right": "\u53f3\u8f6c\u8f66\u9053",
}
_TURN_LANE_INDEX = {"right": 0, "through": 1, "left": 2}
_TURN_ROUTE_SUFFIX = {"left": "left", "through": "through", "right": "right"}
_JUNCTION_NEIGHBORS = {
    "c00": {"north": "n0", "south": "c01", "west": "w0", "east": "c10"},
    "c10": {"north": "n1", "south": "c11", "west": "c00", "east": "e0"},
    "c01": {"north": "c00", "south": "s0", "west": "w1", "east": "c11"},
    "c11": {"north": "c10", "south": "s1", "west": "c01", "east": "e1"},
}
_TURN_EXIT_SIDE = {
    "north": {"right": "west", "through": "south", "left": "east"},
    "south": {"right": "east", "through": "north", "left": "west"},
    "west": {"right": "south", "through": "east", "left": "north"},
    "east": {"right": "north", "through": "west", "left": "south"},
}
_EXTERNAL_FLOW_ORIGINS = {"n0", "n1", "s0", "s1", "w0", "w1", "e0", "e1"}


def _extract_lane_movement(incident_text: str) -> tuple[str, str] | None:
    for movement, keywords in _TURN_KEYWORDS.items():
        if any(keyword in incident_text for keyword in keywords):
            return movement, _TURN_LABELS[movement]
    lowered = incident_text.lower()
    english_map = {
        "left lane": ("left", _TURN_LABELS["left"]),
        "through lane": ("through", _TURN_LABELS["through"]),
        "straight lane": ("through", _TURN_LABELS["through"]),
        "right lane": ("right", _TURN_LABELS["right"]),
    }
    for keyword, payload in english_map.items():
        if keyword in lowered:
            return payload
    return None


def _build_turn_route_edges(target_key: str, incoming_edge: str, movement: str) -> str:
    junction_id, approach = target_key.split("_", 1)
    exit_side = _TURN_EXIT_SIDE.get(approach, {}).get(movement)
    neighbor = _JUNCTION_NEIGHBORS.get(junction_id, {}).get(exit_side or "")
    if not exit_side or not neighbor:
        return incoming_edge
    return f"{incoming_edge} {junction_id}_{neighbor}"


def _resolve_turn_route_prefixes(target_plan: dict, movement: str) -> list[str]:
    lane_ids = target_plan.get("lane_ids") or []
    if not lane_ids:
        return target_plan.get("route_prefixes", [])
    inbound_edge = lane_ids[0].rsplit("_", 1)[0]
    origin_node = inbound_edge.split("_", 1)[0]
    if origin_node in _EXTERNAL_FLOW_ORIGINS:
        return [f"flow_{origin_node}_{_TURN_ROUTE_SUFFIX[movement]}"]
    return target_plan.get("route_prefixes", [])


def _apply_turn_specific_target(target_plan: dict, incident_text: str) -> dict:
    movement_payload = _extract_lane_movement(incident_text)
    if not movement_payload:
        return target_plan

    movement, movement_label = movement_payload
    lane_ids = target_plan.get("lane_ids") or []
    if not lane_ids:
        return target_plan

    lane_index = _TURN_LANE_INDEX[movement]
    selected_lane_ids = [lane_id for lane_id in lane_ids if lane_id.endswith(f"_{lane_index}")]
    if not selected_lane_ids:
        return target_plan

    updated = dict(target_plan)
    updated["lane_ids"] = selected_lane_ids
    updated["target_label"] = f"{target_plan.get('target_label', '目标进口')}{movement_label}"
    updated["route_prefixes"] = _resolve_turn_route_prefixes(target_plan, movement)

    if target_plan.get("target_key", "").startswith("c"):
        blocked_lane_id = selected_lane_ids[0]
        incoming_edge = blocked_lane_id.rsplit("_", 1)[0]
        updated["blocked_lane_id"] = blocked_lane_id
        updated["blocked_lane_label"] = updated["target_label"]
        updated["route_edges"] = _build_turn_route_edges(target_plan["target_key"], incoming_edge, movement)

    updated["movement_key"] = movement
    updated["movement_label"] = movement_label
    return updated


def infer_target_plan(incident_text: str, scenario: str | None) -> dict:
    scenario_text = (scenario or "").lower()
    map_plan = _target_plan_from_map_context(incident_text, scenario_text)
    if map_plan:
        return map_plan

    if "nanjing_south" in scenario_text or "ride_hailing" in scenario_text or "南京南站" in incident_text:
        return _target_plan(
            "nanjing_south_station",
            "南京南站网约车上客区",
            "station_circulation",
            "站区集散交通",
            [],
            ["rh_"],
        )

    for (junction_label, approach_label), payload in _PRECISE_APPROACH_MAP.items():
        if junction_label in incident_text and approach_label in incident_text:
            base_plan = _target_plan(
                payload["target_key"],
                payload["target_label"],
                payload["axis_key"],
                payload["axis_label"],
                payload["lane_ids"],
                payload["route_prefixes"],
            )
            base_plan["route_edges"] = payload["route_edges"]
            return _apply_turn_specific_target(base_plan, incident_text)

    lowered = incident_text.lower()
    east_lanes = ["e0_c10_0", "e0_c10_1", "e0_c10_2", "e1_c11_0", "e1_c11_1", "e1_c11_2"]
    west_lanes = ["w0_c00_0", "w0_c00_1", "w0_c00_2", "w1_c01_0", "w1_c01_1", "w1_c01_2"]
    north_lanes = ["n0_c00_0", "n0_c00_1", "n0_c00_2", "n1_c10_0", "n1_c10_1", "n1_c10_2"]
    south_lanes = ["s0_c01_0", "s0_c01_1", "s0_c01_2", "s1_c11_0", "s1_c11_1", "s1_c11_2"]

    if "\u4e1c\u8fdb\u53e3" in incident_text or "east" in lowered:
        return _apply_turn_specific_target(
            _target_plan("east", "\u4e1c\u4fa7\u8fdb\u53e3\u7fa4", "east_west", "\u4e1c\u897f\u5411", east_lanes, ["flow_e0_", "flow_e1_"]),
            incident_text,
        )
    if "\u897f\u8fdb\u53e3" in incident_text or "west" in lowered:
        return _apply_turn_specific_target(
            _target_plan("west", "\u897f\u4fa7\u8fdb\u53e3\u7fa4", "east_west", "\u4e1c\u897f\u5411", west_lanes, ["flow_w0_", "flow_w1_"]),
            incident_text,
        )
    if "\u5317\u8fdb\u53e3" in incident_text or "north" in lowered:
        return _apply_turn_specific_target(
            _target_plan("north", "\u5317\u4fa7\u8fdb\u53e3\u7fa4", "north_south", "\u5357\u5317\u5411", north_lanes, ["flow_n0_", "flow_n1_"]),
            incident_text,
        )
    if "\u5357\u8fdb\u53e3" in incident_text or "south" in lowered:
        return _apply_turn_specific_target(
            _target_plan("south", "\u5357\u4fa7\u8fdb\u53e3\u7fa4", "north_south", "\u5357\u5317\u5411", south_lanes, ["flow_s0_", "flow_s1_"]),
            incident_text,
        )
    return _apply_turn_specific_target(
        _target_plan(
            "east_west",
            "\u4e1c\u897f\u5411\u8d70\u5eca",
            "east_west",
            "\u4e1c\u897f\u5411",
            west_lanes + east_lanes,
            ["flow_w0_", "flow_w1_", "flow_e0_", "flow_e1_"],
        ),
        incident_text,
    )


def infer_incident_context(incident_text: str, target_plan: dict) -> dict:
    lowered = incident_text.lower()
    incident_type = None
    incident_type_label = None
    if any(word in incident_text or word in lowered for word in ["\u8ffd\u5c3e", "rear-end"]):
        incident_type = "rear_end"
        incident_type_label = "\u8ffd\u5c3e\u4e8b\u6545"
    elif any(word in incident_text or word in lowered for word in ["\u78b0\u649e", "collision"]):
        incident_type = "collision"
        incident_type_label = "\u78b0\u649e\u4e8b\u6545"
    elif any(word in incident_text or word in lowered for word in ["\u629b\u951a", "breakdown"]):
        incident_type = "breakdown"
        incident_type_label = "\u8f66\u8f86\u6545\u969c"
    elif any(word in incident_text or word in lowered for word in ["\u62e5\u5835", "\u6392\u961f", "queue", "congestion"]):
        incident_type = "congestion"
        incident_type_label = "\u62e5\u5835/\u6392\u961f"

    duration_match = re.search(r"(?:\u6301\u7eed|\u4e8b\u6545\u6301\u7eed)\s*(\d{1,3})\s*\u5206\u949f", incident_text)
    incident_duration_minutes = int(duration_match.group(1)) if duration_match else None

    closure_match = re.search(r"\u5c01\u95ed\s*(\d+)\s*\u6761", incident_text)
    lane_closure_count = int(closure_match.group(1)) if closure_match else 0

    blocked_lane_id = _default_blocked_lane_id(target_plan)
    route_edges = target_plan.get("route_edges") or "e0_c10 c10_c00"
    blocked_lane_label = target_plan.get("blocked_lane_label") or target_plan.get("target_label")
    closed_lane_ids = _resolve_closed_lane_ids(target_plan, blocked_lane_id, lane_closure_count)
    blocked_edge_id = blocked_lane_id.rsplit("_", 1)[0] if blocked_lane_id else ""

    apply_scene_edit = bool(incident_type and lane_closure_count > 0 and incident_duration_minutes)
    return {
        "apply_scene_edit": apply_scene_edit,
        "incident_type": incident_type,
        "incident_type_label": incident_type_label,
        "incident_duration_minutes": incident_duration_minutes,
        "lane_closure_count": lane_closure_count,
        "blocked_lane_id": blocked_lane_id,
        "blocked_lane_label": blocked_lane_label,
        "closed_lane_ids": closed_lane_ids,
        "blocked_edge_id": blocked_edge_id,
        "route_id": target_plan.get("target_key", "incident_route"),
        "route_edges": route_edges,
        "movement_key": target_plan.get("movement_key"),
        "movement_label": target_plan.get("movement_label"),
    }


def _default_blocked_lane_id(target_plan: dict) -> str:
    if target_plan.get("blocked_lane_id"):
        return target_plan["blocked_lane_id"]

    lane_ids = target_plan.get("lane_ids") or []
    if not lane_ids:
        return ""

    # For coarse approach inputs, prefer a through lane. Closing a turn-only lane
    # can invalidate fixed turn routes before the simulation starts.
    first_edge = lane_ids[0].rsplit("_", 1)[0]
    through_lane = f"{first_edge}_1"
    if through_lane in lane_ids:
        return through_lane
    return lane_ids[0]


def _resolve_closed_lane_ids(target_plan: dict, blocked_lane_id: str, lane_closure_count: int) -> list[str]:
    if not blocked_lane_id:
        return []
    lane_closure_count = max(1, lane_closure_count)
    edge_id, lane_index_text = blocked_lane_id.rsplit("_", 1)
    try:
        blocked_lane_index = int(lane_index_text)
    except ValueError:
        return [blocked_lane_id]

    same_edge_lane_ids = sorted(
        {
            lane_id
            for lane_id in (target_plan.get("available_lane_ids") or target_plan.get("lane_ids") or [])
            if lane_id.startswith(f"{edge_id}_")
        }
        or {f"{edge_id}_0", f"{edge_id}_1", f"{edge_id}_2"}
    )
    available_indices = []
    for lane_id in same_edge_lane_ids:
        try:
            available_indices.append(int(lane_id.rsplit("_", 1)[1]))
        except ValueError:
            continue
    if blocked_lane_index not in available_indices:
        available_indices.append(blocked_lane_index)

    ordered_indices = sorted(set(available_indices), key=lambda idx: (abs(idx - blocked_lane_index), idx))
    selected_indices = ordered_indices[: min(lane_closure_count, len(ordered_indices))]
    return [f"{edge_id}_{lane_index}" for lane_index in selected_indices]


def _target_plan_from_map_context(incident_text: str, scenario_text: str) -> dict | None:
    map_edge_match = re.search(r"地图道路ID：([^\s]+)", incident_text)
    if not map_edge_match:
        return None

    map_lane_match = re.search(r"地图车道ID：([^\s]+)", incident_text)
    map_lanes_match = re.search(r"地图道路全部车道：([^\s]*)", incident_text)
    map_name_match = re.search(r"地图对象名称：([^\r\n]+)", incident_text)
    edge_id = map_edge_match.group(1).strip()
    selected_lane_id = map_lane_match.group(1).strip() if map_lane_match else ""
    available_lane_ids = [
        lane_id.strip()
        for lane_id in (map_lanes_match.group(1).split(",") if map_lanes_match else [])
        if lane_id.strip()
    ]
    if selected_lane_id and selected_lane_id not in available_lane_ids:
        available_lane_ids.insert(0, selected_lane_id)
    target_lane_ids = [selected_lane_id] if selected_lane_id else available_lane_ids
    target_label = map_name_match.group(1).strip() if map_name_match else f"地图选定道路 {edge_id}"
    plan = _target_plan(
        f"map_{re.sub(r'[^0-9A-Za-z]+', '_', edge_id).strip('_') or 'edge'}",
        target_label,
        "station_circulation",
        "地图选定道路/车道",
        target_lane_ids,
        ["rh_"] if "nanjing_south" in scenario_text or "ride_hailing" in scenario_text else [],
    )
    plan["available_lane_ids"] = available_lane_ids
    plan["blocked_lane_id"] = selected_lane_id
    plan["blocked_lane_label"] = target_label
    plan["route_edges"] = edge_id
    plan["selected_edge_id"] = edge_id
    return plan
