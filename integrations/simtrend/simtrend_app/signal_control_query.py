from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from simtrend_app.config import Settings
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.tools.base import ToolResult


def query_signal_control(
    settings: Settings,
    query: str = "",
    controller_id: str | None = None,
    edge_id: str | None = None,
    lane_id: str | None = None,
    program_id: str = "0",
) -> ToolResult:
    runtime = ScenarioRuntime.from_project_dir(settings.sumo_project_dir)
    try:
        index = build_signal_control_index(runtime)
    except (FileNotFoundError, ET.ParseError, OSError) as exc:
        return ToolResult(
            ok=False,
            message=f"信号控制信息读取失败：{exc}",
            data={"error": {"code": "SIGNAL_INDEX_FAILED", "message": str(exc), "recoverable": True}},
        )

    selection = _resolve_query_selection(
        query,
        index,
        controller_id=controller_id,
        edge_id=edge_id,
        lane_id=lane_id,
    )
    if selection["kind"] == "list":
        controllers = list(index["controllers"].values())
        return ToolResult(
            ok=True,
            message=_format_controller_list(runtime, controllers),
            data={
                "workflow_type": "signal_control_query",
                "query_status": "list",
                "controllers": controllers,
                "signal_context": {},
                "spatial_selection": {},
            },
        )

    controller_keys = selection.get("controller_keys", [])
    if program_id and selection["kind"] == "controller":
        filtered = [key for key in controller_keys if key[1] == str(program_id)]
        if filtered:
            controller_keys = filtered
    if not controller_keys:
        selected_object_id = selection.get("lane_id") or selection.get("edge_id") or ""
        selected_object_exists = (
            selection["kind"] == "lane" and selected_object_id in index["lanes"]
        ) or (
            selection["kind"] == "edge" and selected_object_id in index["edges"]
        )
        if selected_object_exists:
            object_label = "车道" if selection["kind"] == "lane" else "道路"
            controlled_examples = [
                index["edges"][edge_value]
                for edge_value in sorted(index["edge_to_controller_keys"])[:4]
                if edge_value in index["edges"]
            ]
            example_text = "、".join(
                f"{item['display_name']}（`{item['edge_id']}`）" for item in controlled_examples
            )
            return ToolResult(
                ok=True,
                message=(
                    "**信号控制查询结果**\n\n"
                    f"查询对象：{object_label} `{selected_object_id}`。\n\n"
                    "**结论：该对象未由信号控制器直接管理，因此没有可查询的信号相位方案。**\n\n"
                    "这通常表示它是交叉口出口、普通路段，或位于非信号控制节点。"
                    + (f"当前场景受控进口道路示例：{example_text}。" if example_text else "")
                ),
                data={
                    "workflow_type": "signal_control_query",
                    "query_status": "uncontrolled",
                    "controllers": [],
                    "signal_context": {},
                    "spatial_selection": {},
                },
            )
        examples = "、".join(item["controller_id"] for item in list(index["controllers"].values())[:4])
        return ToolResult(
            ok=False,
            message=(
                "**信号控制查询结果**\n\n"
                "没有找到与输入匹配的信号控制器、道路或车道。"
                f"当前场景控制器示例：{examples or '无'}。"
            ),
            data={
                "workflow_type": "signal_control_query",
                "query_status": "not_found",
                "error": {
                    "code": "SIGNAL_CONTROLLER_NOT_FOUND",
                    "message": "未找到匹配的信号控制对象",
                    "recoverable": True,
                },
            },
        )

    controllers = [index["controllers"][key] for key in controller_keys]
    preferred_edge = selection.get("edge_id", "")
    primary = controllers[0]
    spatial_selection = _build_spatial_selection(runtime, primary, preferred_edge, index)
    status = "matched" if len(controllers) == 1 else "multiple"
    return ToolResult(
        ok=True,
        message=_format_controller_detail(runtime, controllers, selection),
        data={
            "workflow_type": "signal_control_query",
            "query_status": status,
            "controllers": controllers,
            "signal_context": primary if len(controllers) == 1 else {"candidates": controllers},
            "spatial_selection": spatial_selection,
        },
    )


def build_signal_control_index(runtime: ScenarioRuntime) -> dict[str, Any]:
    root = ET.parse(runtime.net_file).getroot()
    intersection_names = {
        str(item.get("id")): str(item.get("name"))
        for item in runtime.intersections
        if item.get("id")
    }
    edges = {}
    lanes = {}
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if not edge_id or edge_id.startswith(":") or edge.get("function") == "internal":
            continue
        lane_ids = [lane.get("id", "") for lane in edge.findall("lane") if lane.get("id")]
        edge_row = {
            "edge_id": edge_id,
            "display_name": edge.get("name") or f"道路 {edge_id}",
            "lane_ids": lane_ids,
            "from_node": edge.get("from", ""),
            "to_node": edge.get("to", ""),
        }
        edges[edge_id] = edge_row
        for lane_id_value in lane_ids:
            lanes[lane_id_value] = {"lane_id": lane_id_value, "edge_id": edge_id}

    connections_by_tls: dict[str, list[dict]] = {}
    edge_to_controller_keys: dict[str, set[tuple[str, str]]] = {}
    lane_to_controller_keys: dict[str, set[tuple[str, str]]] = {}
    for connection in root.findall("connection"):
        tls_id = connection.get("tl", "")
        if not tls_id:
            continue
        from_edge = connection.get("from", "")
        to_edge = connection.get("to", "")
        from_lane_index = _integer(connection.get("fromLane"))
        lane_ids = edges.get(from_edge, {}).get("lane_ids", [])
        from_lane_id = lane_ids[from_lane_index] if 0 <= from_lane_index < len(lane_ids) else ""
        row = {
            "link_index": _integer(connection.get("linkIndex")),
            "from_edge_id": from_edge,
            "from_edge_name": edges.get(from_edge, {}).get("display_name", f"道路 {from_edge}"),
            "from_lane_id": from_lane_id,
            "to_edge_id": to_edge,
            "to_edge_name": edges.get(to_edge, {}).get("display_name", f"道路 {to_edge}"),
            "to_lane_index": _integer(connection.get("toLane")),
        }
        connections_by_tls.setdefault(tls_id, []).append(row)

    controllers: dict[tuple[str, str], dict] = {}
    for tl_logic in root.findall("tlLogic"):
        tls_id = tl_logic.get("id", "")
        program = tl_logic.get("programID", "0")
        key = (tls_id, program)
        connections = sorted(
            connections_by_tls.get(tls_id, []),
            key=lambda item: (item["link_index"], item["from_edge_id"], item["to_edge_id"]),
        )
        phase_rows = []
        for phase_index, phase in enumerate(tl_logic.findall("phase")):
            state = phase.get("state", "")
            active_connections = [
                connection
                for connection in connections
                if 0 <= connection["link_index"] < len(state)
                and state[connection["link_index"]] in "Gg"
            ]
            phase_rows.append(
                {
                    "phase_index": phase_index,
                    "duration_s": _number(phase.get("duration")),
                    "state": state,
                    "phase_type": _phase_type(state),
                    "active_link_indices": sorted({item["link_index"] for item in active_connections}),
                    "active_connections": active_connections,
                }
            )
        controlled_edge_ids = sorted({item["from_edge_id"] for item in connections if item["from_edge_id"]})
        controlled_lane_ids = sorted({item["from_lane_id"] for item in connections if item["from_lane_id"]})
        controller = {
            "controller_id": tls_id,
            "display_name": intersection_names.get(tls_id) or f"信号控制器 {tls_id}",
            "program_id": program,
            "controller_type": tl_logic.get("type", "static"),
            "offset_s": _number(tl_logic.get("offset")),
            "cycle_seconds": round(sum(row["duration_s"] for row in phase_rows), 3),
            "phase_count": len(phase_rows),
            "phase_durations_s": [row["duration_s"] for row in phase_rows],
            "phases": phase_rows,
            "controlled_connection_count": len(connections),
            "controlled_edge_ids": controlled_edge_ids,
            "controlled_lane_ids": controlled_lane_ids,
        }
        controllers[key] = controller
        for edge_id in controlled_edge_ids:
            edge_to_controller_keys.setdefault(edge_id, set()).add(key)
        for lane_id_value in controlled_lane_ids:
            lane_to_controller_keys.setdefault(lane_id_value, set()).add(key)

    return {
        "controllers": controllers,
        "edges": edges,
        "lanes": lanes,
        "edge_to_controller_keys": edge_to_controller_keys,
        "lane_to_controller_keys": lane_to_controller_keys,
    }


def _resolve_query_selection(
    query: str,
    index: dict,
    *,
    controller_id: str | None,
    edge_id: str | None,
    lane_id: str | None,
) -> dict:
    if controller_id:
        keys = [key for key in index["controllers"] if key[0] == controller_id]
        return {"kind": "controller", "controller_keys": keys, "controller_id": controller_id}
    if lane_id:
        keys = sorted(index["lane_to_controller_keys"].get(lane_id, set()))
        edge_value = index["lanes"].get(lane_id, {}).get("edge_id", "")
        return {"kind": "lane", "controller_keys": keys, "lane_id": lane_id, "edge_id": edge_value}
    if edge_id:
        keys = sorted(index["edge_to_controller_keys"].get(edge_id, set()))
        return {"kind": "edge", "controller_keys": keys, "edge_id": edge_id}

    for key in sorted(index["controllers"], key=lambda item: len(item[0]), reverse=True):
        explicit_pattern = (
            r"(?:信号)?控制器(?:\s*ID)?\s*(?:为|是|[:：])?\s*[`\"]?"
            + re.escape(key[0])
            + r"(?:[`\"]|\s|$|[，。？?,])"
        )
        if key[0] and re.search(explicit_pattern, query, flags=re.I):
            return {"kind": "controller", "controller_keys": [key], "controller_id": key[0]}
    for lane_value in sorted(index["lanes"], key=len, reverse=True):
        if lane_value and lane_value in query:
            keys = sorted(index["lane_to_controller_keys"].get(lane_value, set()))
            return {
                "kind": "lane",
                "controller_keys": keys,
                "lane_id": lane_value,
                "edge_id": index["lanes"][lane_value]["edge_id"],
            }
    hidden_edge_match = re.search(r"地图道路ID：\s*([^\s\n]+)", query)
    if hidden_edge_match and hidden_edge_match.group(1) in index["edges"]:
        value = hidden_edge_match.group(1)
        return {
            "kind": "edge",
            "controller_keys": sorted(index["edge_to_controller_keys"].get(value, set())),
            "edge_id": value,
        }
    for edge_value in sorted(index["edges"], key=len, reverse=True):
        edge_name = index["edges"][edge_value]["display_name"]
        if edge_value in query or (not edge_name.startswith("道路 ") and edge_name in query):
            keys = sorted(index["edge_to_controller_keys"].get(edge_value, set()))
            return {"kind": "edge", "controller_keys": keys, "edge_id": edge_value}
    for key in sorted(index["controllers"], key=lambda item: len(item[0]), reverse=True):
        if key[0] and key[0] in query:
            return {"kind": "controller", "controller_keys": [key], "controller_id": key[0]}
    return {"kind": "list" if _is_list_query(query) else "not_found", "controller_keys": []}


def _is_list_query(query: str) -> bool:
    return not query.strip() or any(word in query for word in ("有哪些", "全部", "所有", "列出", "控制器列表"))


def _format_controller_list(runtime: ScenarioRuntime, controllers: list[dict]) -> str:
    lines = [
        "**当前场景信号控制器概览**",
        "",
        f"场景：{runtime.name}；共识别到 **{len(controllers)}** 个信号控制程序。",
        "",
        "| 控制器 | 程序 | 类型 | 相位数 | 周期 | 受控进口道路 |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for item in controllers:
        lines.append(
            f"| {item['display_name']} (`{item['controller_id']}`) | `{item['program_id']}` | "
            f"{item['controller_type']} | {item['phase_count']} | {item['cycle_seconds']:g} 秒 | "
            f"{len(item['controlled_edge_ids'])} |"
        )
    lines.extend(["", "可以继续输入控制器 ID、道路 ID 或车道 ID 查看相位和受控连接详情。"])
    return "\n".join(lines)


def _format_controller_detail(runtime: ScenarioRuntime, controllers: list[dict], selection: dict) -> str:
    lines = ["**信号控制器与相位查询结果**", ""]
    if selection["kind"] in {"edge", "lane"}:
        object_id = selection.get("lane_id") or selection.get("edge_id")
        lines.append(f"查询对象：`{object_id}`；匹配到 {len(controllers)} 个控制程序。")
        lines.append("")
    for controller_index, item in enumerate(controllers):
        if controller_index:
            lines.extend(["", "---", ""])
        lines.extend(
            [
                f"控制器：**{item['display_name']}** (`{item['controller_id']}`)",
                f"程序：`{item['program_id']}`；类型：{item['controller_type']}；"
                f"周期：{item['cycle_seconds']:g} 秒；相位数：{item['phase_count']}。",
                f"受控范围：{len(item['controlled_edge_ids'])} 条进口道路、"
                f"{len(item['controlled_lane_ids'])} 条车道、{item['controlled_connection_count']} 条转向连接。",
                "",
                "| 相位 | 类型 | 时长 | 灯色状态 | 放行连接数 | 主要放行连接 |",
                "|---:|---|---:|---|---:|---|",
            ]
        )
        for phase in item["phases"]:
            movements = [
                f"{row['from_edge_id']} → {row['to_edge_id']}"
                for row in phase["active_connections"]
            ]
            movement_text = "；".join(movements[:4]) or "无绿灯放行连接"
            if len(movements) > 4:
                movement_text += f"；另 {len(movements) - 4} 条"
            lines.append(
                f"| {phase['phase_index']} | {_phase_type_label(phase['phase_type'])} | "
                f"{phase['duration_s']:g} 秒 | `{phase['state']}` | "
                f"{len(phase['active_connections'])} | {movement_text} |"
            )
        durations = "、".join(f"{value:g}" for value in item["phase_durations_s"])
        lines.extend(
            [
                "",
                "**可直接验证的参数模板**",
                "",
                f"`控制器 {item['controller_id']} 的相位时长设为 {durations}，运行600秒仿真，随机种子42`",
            ]
        )
    lines.extend(["", "说明：本工具只读取当前路网信号定义，不运行仿真，也不判断现有配时是否合理。"])
    return "\n".join(lines)


def _build_spatial_selection(
    runtime: ScenarioRuntime,
    controller: dict,
    preferred_edge: str,
    index: dict,
) -> dict:
    controlled_edges = controller.get("controlled_edge_ids", [])
    selected_edge = preferred_edge if preferred_edge in controlled_edges else (controlled_edges[0] if controlled_edges else "")
    if not selected_edge:
        return {}
    edge = index["edges"].get(selected_edge, {})
    lane_ids = edge.get("lane_ids", [])
    return {
        "scenario_id": runtime.scenario_id,
        "selector_key": f"edge:{selected_edge}",
        "object_type": "road",
        "display_name": edge.get("display_name", f"道路 {selected_edge}"),
        "edge_id": selected_edge,
        "lane_id": lane_ids[0] if lane_ids else "",
        "lane_ids": lane_ids,
        "signal_controller_id": controller["controller_id"],
    }


def _phase_type(state: str) -> str:
    if any(char in state for char in "Gg"):
        return "green"
    if any(char in state for char in "yY"):
        return "yellow"
    return "all_red"


def _phase_type_label(value: str) -> str:
    return {"green": "放行", "yellow": "黄灯过渡", "all_red": "全红/清空"}[value]


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _number(value: Any) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return 0.0
