from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simtrend_app.map_selector import load_map_objects
from simtrend_app.scenario_runtime import ScenarioRuntime


QUERY_WORDS = (
    "查询",
    "查一下",
    "查看",
    "告诉我",
    "是什么",
    "有哪些",
    "多少",
    "几个",
    "几条",
    "多长",
    "限速",
    "属性",
    "信息",
    "连接",
    "相邻",
    "上游",
    "下游",
    "通向",
    "允许",
    "对应哪",
    "属于哪",
)
SIMULATION_ACTION_WORDS = (
    "仿真",
    "优化",
    "注入",
    "封闭",
    "事故",
    "调整",
    "提高",
    "降低",
    "增加",
    "减少",
    "运行",
)
OBJECT_WORDS = ("道路", "路段", "车道", "路口", "交叉口", "上客区", "停车区", "进口")
LIST_WORDS = ("有哪些", "列出", "列表", "全部", "所有", "多少个", "多少条")
METRIC_WORDS = ("最近", "指标", "速度", "排队", "流量", "车辆数", "等待", "拥堵")


@dataclass(frozen=True)
class NetworkObject:
    object_type: str
    object_id: str
    display_name: str
    edge_id: str = ""
    lane_id: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    attributes: dict[str, Any] = field(default_factory=dict)

    def as_candidate(self) -> dict[str, Any]:
        return {
            "object_type": self.object_type,
            "object_id": self.object_id,
            "display_name": self.display_name,
            "edge_id": self.edge_id,
            "lane_id": self.lane_id,
        }


@dataclass(frozen=True)
class NetworkQueryResult:
    status: str
    query_kind: str
    answer_markdown: str
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    spatial_selection: dict[str, Any] = field(default_factory=dict)

    @property
    def awaiting_clarification(self) -> bool:
        return self.status == "ambiguous"


def looks_like_network_query(text: str, conversation_memory: list[dict] | None = None) -> bool:
    clean_text = _clean_user_text(text)
    latest_network_query = next(
        (
            item
            for item in reversed((conversation_memory or [])[-3:])
            if item.get("task_type") == "network_query"
        ),
        None,
    )
    if latest_network_query and latest_network_query.get("awaiting_network_clarification"):
        return True
    if _looks_like_scene_overview(clean_text):
        return True
    has_query_word = any(word in clean_text for word in QUERY_WORDS) or clean_text.endswith(("吗", "呢", "？", "?"))
    has_object_word = any(word in clean_text for word in OBJECT_WORDS)
    has_simulation_action = any(word in clean_text for word in SIMULATION_ACTION_WORDS)
    explicit_query = any(word in clean_text for word in ("查询", "查一下", "查看", "告诉我"))
    return has_query_word and (has_object_word or _contains_object_id(clean_text)) and (
        not has_simulation_action or explicit_query
    )


class NetworkQueryService:
    def __init__(self, runtime: ScenarioRuntime) -> None:
        self.runtime = runtime
        self.index = _load_network_index(
            str(runtime.net_file.resolve()),
            str(runtime.project_dir.resolve()),
            runtime.scenario_id,
            runtime.intersections,
            runtime.map_config,
        )

    def query(
        self,
        text: str,
        *,
        conversation_memory: list[dict] | None = None,
    ) -> NetworkQueryResult:
        clean_text = _clean_user_text(text)
        if _looks_like_scene_overview(clean_text):
            return self._scene_overview_result()
        if _looks_like_edge_impact_query(clean_text):
            return self._demand_edge_impact_result()
        clarification = self._resolve_clarification(clean_text, conversation_memory or [])
        if clarification:
            return self._detail_result(clarification, query_kind="clarification")

        contextual_object = self._resolve_spatial_context(text, clean_text)
        if contextual_object:
            query_kind = _query_kind(clean_text)
            return self._detail_result(contextual_object, query_kind=query_kind)

        list_type = _requested_list_type(clean_text)
        if list_type:
            return self._list_result(list_type)

        ranked = self._rank_objects(clean_text)
        if not ranked or ranked[0][0] < 24:
            return NetworkQueryResult(
                status="not_found",
                query_kind="search",
                answer_markdown=(
                    "**路网查询结果**\n\n"
                    "没有找到足够可信的路网对象。请补充道路名称、路口名称，或直接输入地图中的道路/车道 ID。"
                ),
            )

        top_score, top_object = ranked[0]
        close_matches = [item for score, item in ranked if score >= top_score - 5]
        close_matches = _deduplicate_candidates(close_matches)[:5]
        if len(close_matches) > 1 and not _has_exact_identifier(clean_text, top_object):
            candidates = tuple(item.as_candidate() for item in close_matches)
            lines = ["**路网查询结果**", "", "找到多个可能对象，请回复“第 1 个”或直接输入对象 ID：", ""]
            for index, item in enumerate(close_matches, start=1):
                identifier = item.lane_id or item.edge_id or item.object_id
                lines.append(f"{index}. {item.display_name}（`{identifier}`）")
            return NetworkQueryResult(
                status="ambiguous",
                query_kind="search",
                answer_markdown="\n".join(lines),
                candidates=candidates,
            )

        query_kind = _query_kind(clean_text)
        return self._detail_result(top_object, query_kind=query_kind)

    def _rank_objects(self, query: str) -> list[tuple[int, NetworkObject]]:
        normalized_query = _normalize(query)
        requested_type = _requested_object_type(query)
        ranked: list[tuple[int, NetworkObject]] = []
        objects = self.index["objects"]
        if requested_type == "junction":
            named_objects = [
                item
                for item in objects
                if item.object_type == "junction" and item.attributes.get("is_named_intersection")
            ]
            if named_objects:
                objects = named_objects
        for item in objects:
            score = _score_object(normalized_query, item, requested_type)
            if score > 0:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].display_name, pair[1].object_id))
        return ranked

    def _resolve_clarification(
        self,
        query: str,
        conversation_memory: list[dict],
    ) -> NetworkObject | None:
        pending = next(
            (
                item
                for item in reversed(conversation_memory[-3:])
                if item.get("awaiting_network_clarification") and item.get("network_query_candidates")
            ),
            None,
        )
        if not pending:
            return None
        candidates = pending["network_query_candidates"]
        choice_match = re.search(r"第\s*(\d+)\s*个", query)
        if choice_match:
            index = int(choice_match.group(1)) - 1
            if 0 <= index < len(candidates):
                return self._find_indexed_object(candidates[index])
        normalized_query = _normalize(query)
        for candidate in candidates:
            identifiers = (candidate.get("object_id"), candidate.get("edge_id"), candidate.get("lane_id"))
            if any(identifier and _normalize(str(identifier)) in normalized_query for identifier in identifiers):
                return self._find_indexed_object(candidate)
        return None

    def _find_indexed_object(self, candidate: dict[str, Any]) -> NetworkObject | None:
        for item in self.index["objects"]:
            if item.object_type == candidate.get("object_type") and item.object_id == candidate.get("object_id"):
                return item
        return None

    def _resolve_spatial_context(self, raw_text: str, clean_text: str) -> NetworkObject | None:
        if not any(word in clean_text for word in ("这条", "这个", "该路", "该车道", "刚才", "当前选择")):
            return None
        edge_match = re.search(r"地图道路ID：\s*([^\s\n]+)", raw_text)
        lane_match = re.search(r"地图车道ID：\s*([^\s\n]+)", raw_text)
        requested_type = _requested_object_type(clean_text)
        preferred_id = lane_match.group(1) if requested_type == "lane" and lane_match else ""
        preferred_id = preferred_id or (edge_match.group(1) if edge_match else "")
        if not preferred_id:
            return None
        for item in self.index["objects"]:
            if preferred_id in (item.object_id, item.lane_id, item.edge_id):
                if requested_type is None or item.object_type == requested_type:
                    return item
        return None

    def _list_result(self, object_type: str) -> NetworkQueryResult:
        objects = [item for item in self.index["objects"] if item.object_type == object_type]
        if object_type == "junction":
            named_objects = [item for item in objects if item.attributes.get("is_named_intersection")]
            if named_objects:
                objects = named_objects
        label = {
            "junction": "路口",
            "pickup_zone": "上客区",
            "road": "道路",
            "lane": "车道",
        }[object_type]
        unique = _deduplicate_candidates(objects)
        lines = [f"**当前场景{label}概览**", "", f"共识别到 **{len(unique)}** 个{label}。"]
        display_limit = 20
        if len(unique) <= display_limit:
            lines.append("")
            for item in unique:
                identifier = item.lane_id or item.edge_id or item.object_id
                lines.append(f"- {item.display_name}（`{identifier}`）")
        else:
            lines.append(f"为避免列表过长，仅展示前 {display_limit} 个；可以继续输入名称或 ID 精确查询。")
            lines.append("")
            for item in unique[:display_limit]:
                identifier = item.lane_id or item.edge_id or item.object_id
                lines.append(f"- {item.display_name}（`{identifier}`）")
        return NetworkQueryResult(
            status="list",
            query_kind="list",
            answer_markdown="\n".join(lines),
            candidates=tuple(item.as_candidate() for item in unique[:display_limit]),
        )

    def _scene_overview_result(self) -> NetworkQueryResult:
        counts = {
            object_type: len(
                _deduplicate_candidates(
                    [item for item in self.index["objects"] if item.object_type == object_type]
                )
            )
            for object_type in ("junction", "road", "lane", "pickup_zone")
        }
        controller_count = int(self.index.get("signal_controller_count") or 0)
        program_count = int(self.index.get("signal_program_count") or 0)
        named_area_count = len(self.runtime.intersections)
        lines = [
            "**当前场景路网概况**",
            "",
            f"场景：**{self.runtime.name}**",
            "",
            "| 对象类型 | 数量 |",
            "|---|---:|",
            f"| 场景命名重点区域/路口 | {named_area_count} |",
            f"| 路网节点（含边界节点） | {counts['junction']} |",
            f"| 道路 | {counts['road']} |",
            f"| 车道 | {counts['lane']} |",
            f"| 信号控制器 | {controller_count} |",
            f"| 信号控制程序 | {program_count} |",
            f"| 上客区/停车空间对象 | {counts['pickup_zone']} |",
            "",
            "统计信息直接读取当前场景路网与场景配置，不运行仿真。",
        ]
        return NetworkQueryResult(
            status="overview",
            query_kind="scene_overview",
            answer_markdown="\n".join(lines),
        )

    def _detail_result(self, item: NetworkObject, *, query_kind: str) -> NetworkQueryResult:
        attributes = item.attributes
        type_label = {
            "junction": "路口",
            "pickup_zone": "上客区",
            "road": "道路",
            "lane": "车道",
        }.get(item.object_type, "空间对象")
        lines = ["**路网查询结果**", "", f"对象：**{item.display_name}**", f"类型：{type_label}"]
        identifier = item.lane_id or item.edge_id or item.object_id
        lines.append(f"对象 ID：`{identifier}`")

        detail_rows = _format_attribute_rows(item)
        if detail_rows:
            lines.extend(["", "| 属性 | 数值 |", "|---|---|"])
            lines.extend(f"| {name} | {value} |" for name, value in detail_rows)

        if query_kind == "connectivity" or item.object_type in {"road", "lane"}:
            predecessors = self._edge_names(attributes.get("predecessor_edge_ids") or [])
            successors = self._edge_names(attributes.get("successor_edge_ids") or [])
            if predecessors or successors:
                lines.extend(["", "**连接关系**"])
                lines.append(f"- 上游道路：{predecessors or '无可用连接'}")
                lines.append(f"- 下游道路：{successors or '无可用连接'}")

        if query_kind == "metrics":
            lines.extend(["", "**最近一次优化仿真指标**", ""])
            metrics = self._latest_metrics(item)
            if metrics.get("available"):
                lines.extend(
                    [
                        f"- 涉及车道：{metrics['lane_count']} 条",
                        f"- 轨迹中的车辆：{metrics['unique_vehicle_count']} 辆",
                        f"- 平均行驶速度：{metrics['average_speed_mps']:.2f} m/s（{metrics['average_speed_mps'] * 3.6:.1f} km/h）",
                        f"- 平均排队长度：{metrics['average_queue_length_m']:.2f} m",
                        f"- 最大排队长度：{metrics['maximum_queue_length_m']:.2f} m",
                        f"- 平均排队时间：{metrics['average_queue_time_s']:.2f} s",
                    ]
                )
                if metrics.get("notes"):
                    lines.append(f"- 数据说明：{metrics['notes']}")
            else:
                lines.append("尚未找到最近一次优化仿真的轨迹与排队输出，请先运行一次仿真。")

        selection = _build_spatial_selection(self.runtime.scenario_id, item, self.index["lanes_by_edge"])
        if selection:
            lines.extend(["", "该对象已同步到空间对象选择器，可直接继续输入事故、需求或优化任务。"])
        return NetworkQueryResult(
            status="matched",
            query_kind=query_kind,
            answer_markdown="\n".join(lines),
            candidates=(item.as_candidate(),),
            spatial_selection=selection,
        )

    def _demand_edge_impact_result(self) -> NetworkQueryResult:
        comparison_file = self._latest_demand_comparison_file()
        if comparison_file is None:
            return NetworkQueryResult(
                status="not_found",
                query_kind="demand_edge_impact",
                answer_markdown=(
                    "**交通需求空间影响查询**\n\n"
                    "尚未找到交通需求影响评估结果。请先运行一次“原始需求与调整后需求对比”仿真。"
                ),
            )
        try:
            payload = json.loads(comparison_file.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return NetworkQueryResult(
                status="not_found",
                query_kind="demand_edge_impact",
                answer_markdown="**交通需求空间影响查询**\n\n最近一次道路影响数据无法读取，请重新运行需求评估。",
            )

        top_edges = (payload.get("edge_impact_summary") or {}).get("top_affected_edges") or []
        if not top_edges:
            return NetworkQueryResult(
                status="not_found",
                query_kind="demand_edge_impact",
                answer_markdown="**交通需求空间影响查询**\n\n最近一次需求评估没有产生有效道路指标。",
            )
        edge_lookup = self.index["edges_by_id"]
        lines = [
            "**交通需求空间影响查询**",
            "",
            "最近一次需求调整后，受影响最大的道路如下：",
            "",
            "| 排名 | 道路 | 影响评分 | 进入车辆变化 | 速度变化 | 时间损失变化 |",
            "|---:|---|---:|---:|---:|---:|",
        ]
        candidates = []
        for index, row in enumerate(top_edges[:10], start=1):
            edge_id = str(row.get("edge_id", ""))
            item = edge_lookup.get(edge_id)
            display_name = item.display_name if item else f"道路 {edge_id}"
            lines.append(
                f"| {index} | {display_name}（`{edge_id}`） | {float(row.get('impact_score', 0)):.1f} | "
                f"{float(row.get('vehicle_entered_delta', 0)):+.0f} 辆 | "
                f"{float(row.get('mean_speed_delta_mps', 0)):+.2f} m/s | "
                f"{float(row.get('time_loss_delta_s', 0)):+.1f} s |"
            )
            if item:
                candidates.append(item.as_candidate())
        lines.extend(
            [
                "",
                "影响评分综合考虑进入车辆增长、平均速度下降和时间损失增加；可继续输入道路 ID 查询详细信息。",
            ]
        )
        return NetworkQueryResult(
            status="list",
            query_kind="demand_edge_impact",
            answer_markdown="\n".join(lines),
            candidates=tuple(candidates),
        )

    def _latest_demand_comparison_file(self) -> Path | None:
        if not self.runtime.agent_runs_dir.exists():
            return None
        run_dirs = sorted(
            (path for path in self.runtime.agent_runs_dir.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for run_dir in run_dirs:
            candidate = run_dir / "json" / "demand_comparison.json"
            if candidate.exists():
                return candidate
        return None

    def _latest_metrics(self, item: NetworkObject) -> dict[str, Any]:
        lane_ids = self._target_lane_ids(item)
        optimized_dir = self.runtime.agent_runs_dir / "latest_run" / "optimized"
        fcd_file = optimized_dir / "fcd.xml"
        queue_file = optimized_dir / "queue.xml"
        if not lane_ids or (not fcd_file.exists() and not queue_file.exists()):
            return {"available": False}

        speed_sum = 0.0
        vehicle_observations = 0
        unique_vehicle_ids: set[str] = set()
        if fcd_file.exists():
            try:
                for _, element in ET.iterparse(fcd_file, events=("end",)):
                    if element.tag == "vehicle" and element.get("lane") in lane_ids:
                        speed_sum += _to_float(element.get("speed"))
                        vehicle_observations += 1
                        if element.get("id"):
                            unique_vehicle_ids.add(str(element.get("id")))
                    element.clear()
            except ET.ParseError:
                pass

        queue_lengths: list[float] = []
        queue_times: list[float] = []
        if queue_file.exists():
            try:
                for _, element in ET.iterparse(queue_file, events=("end",)):
                    if element.tag == "lane" and element.get("id") in lane_ids:
                        queue_lengths.append(_to_float(element.get("queueing_length")))
                        queue_times.append(_to_float(element.get("queueing_time")))
                    element.clear()
            except ET.ParseError:
                pass

        notes = "速度按 FCD 车辆时刻记录计算，排队指标按 queue-output 车道时刻记录计算。"
        return {
            "available": bool(vehicle_observations or queue_lengths),
            "lane_count": len(lane_ids),
            "unique_vehicle_count": len(unique_vehicle_ids),
            "average_speed_mps": speed_sum / vehicle_observations if vehicle_observations else 0.0,
            "average_queue_length_m": sum(queue_lengths) / len(queue_lengths) if queue_lengths else 0.0,
            "maximum_queue_length_m": max(queue_lengths, default=0.0),
            "average_queue_time_s": sum(queue_times) / len(queue_times) if queue_times else 0.0,
            "notes": notes,
        }

    def _target_lane_ids(self, item: NetworkObject) -> set[str]:
        if item.lane_id:
            return {item.lane_id}
        if item.edge_id:
            return {lane.lane_id for lane in self.index["lanes_by_edge"].get(item.edge_id, [])}
        if item.object_type == "junction":
            edge_ids = item.attributes.get("incoming_edge_ids") or []
            return {
                lane.lane_id
                for edge_id in edge_ids
                for lane in self.index["lanes_by_edge"].get(edge_id, [])
            }
        return set()

    def _edge_names(self, edge_ids: list[str]) -> str:
        edge_lookup = self.index["edges_by_id"]
        values = []
        for edge_id in edge_ids[:8]:
            item = edge_lookup.get(edge_id)
            values.append(f"{item.display_name}（`{edge_id}`）" if item else f"`{edge_id}`")
        if len(edge_ids) > 8:
            values.append(f"另有 {len(edge_ids) - 8} 条")
        return "、".join(values)


def _load_network_index(
    net_path_text: str,
    project_path_text: str,
    scenario_id: str,
    intersections: tuple[dict, ...],
    map_config: dict,
) -> dict[str, Any]:
    return _build_network_index(
        Path(net_path_text),
        Path(project_path_text),
        scenario_id,
        intersections,
        map_config,
    )


def _build_network_index(
    net_file: Path,
    project_dir: Path,
    scenario_id: str,
    intersections: tuple[dict, ...],
    map_config: dict,
) -> dict[str, Any]:
    root = ET.parse(net_file).getroot()
    map_names: dict[str, str] = {}
    try:
        map_edges, _ = load_map_objects(project_dir, map_config)
        map_names = {item["edge_id"]: item.get("edge_name") or "" for item in map_edges}
    except (KeyError, OSError, ET.ParseError):
        pass

    predecessor_ids: dict[str, set[str]] = {}
    successor_ids: dict[str, set[str]] = {}
    for connection in root.findall("connection"):
        from_edge = connection.get("from", "")
        to_edge = connection.get("to", "")
        if not from_edge or not to_edge or from_edge.startswith(":") or to_edge.startswith(":"):
            continue
        successor_ids.setdefault(from_edge, set()).add(to_edge)
        predecessor_ids.setdefault(to_edge, set()).add(from_edge)

    objects: list[NetworkObject] = []
    lanes_by_edge: dict[str, list[NetworkObject]] = {}
    edges_by_id: dict[str, NetworkObject] = {}
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if not edge_id or edge_id.startswith(":") or edge.get("function") == "internal":
            continue
        lanes = list(edge.findall("lane"))
        if not lanes:
            continue
        edge_name = edge.get("name") or map_names.get(edge_id) or f"道路 {edge_id}"
        lane_count = len(lanes)
        length_m = max((_to_float(lane.get("length")) for lane in lanes), default=0.0)
        speed_limit = max((_to_float(lane.get("speed")) for lane in lanes), default=0.0)
        edge_object = NetworkObject(
            object_type="road",
            object_id=edge_id,
            display_name=edge_name,
            edge_id=edge_id,
            aliases=(edge_id, edge_name),
            attributes={
                "from_node": edge.get("from", ""),
                "to_node": edge.get("to", ""),
                "road_type": edge.get("type", ""),
                "priority": edge.get("priority", ""),
                "lane_count": lane_count,
                "length_m": length_m,
                "speed_limit_mps": speed_limit,
                "predecessor_edge_ids": sorted(predecessor_ids.get(edge_id, set())),
                "successor_edge_ids": sorted(successor_ids.get(edge_id, set())),
            },
        )
        objects.append(edge_object)
        edges_by_id[edge_id] = edge_object

        lane_objects: list[NetworkObject] = []
        for lane in lanes:
            lane_id = lane.get("id", "")
            lane_index = int(lane.get("index") or len(lane_objects))
            movement_label = _movement_label(scenario_id, lane_index, lane_count)
            display_name = f"{edge_name}{movement_label}车道" if movement_label else f"{edge_name}车道 {lane_index + 1}"
            lane_object = NetworkObject(
                object_type="lane",
                object_id=lane_id,
                display_name=display_name,
                edge_id=edge_id,
                lane_id=lane_id,
                aliases=(lane_id, edge_id, edge_name, display_name),
                attributes={
                    "lane_index": lane_index,
                    "movement_label": movement_label,
                    "length_m": _to_float(lane.get("length")),
                    "speed_limit_mps": _to_float(lane.get("speed")),
                    "width_m": _to_float(lane.get("width")),
                    "allow": lane.get("allow", ""),
                    "disallow": lane.get("disallow", ""),
                    "predecessor_edge_ids": sorted(predecessor_ids.get(edge_id, set())),
                    "successor_edge_ids": sorted(successor_ids.get(edge_id, set())),
                },
            )
            objects.append(lane_object)
            lane_objects.append(lane_object)
        lanes_by_edge[edge_id] = lane_objects

    intersection_names = {str(item.get("id")): str(item.get("name") or item.get("id")) for item in intersections}
    for junction in root.findall("junction"):
        junction_id = junction.get("id", "")
        if not junction_id or junction_id.startswith(":"):
            continue
        display_name = intersection_names.get(junction_id) or f"路口 {junction_id}"
        incoming_lanes = [value for value in (junction.get("incLanes") or "").split() if not value.startswith(":")]
        incoming_edges = sorted({lane_id.rsplit("_", 1)[0] for lane_id in incoming_lanes})
        outgoing_edges = sorted(
            edge_id for edge_id, edge_object in edges_by_id.items() if edge_object.attributes.get("from_node") == junction_id
        )
        objects.append(
            NetworkObject(
                object_type="junction",
                object_id=junction_id,
                display_name=display_name,
                aliases=(junction_id, display_name),
                attributes={
                    "is_named_intersection": junction_id in intersection_names,
                    "junction_type": junction.get("type", ""),
                    "incoming_edge_ids": incoming_edges,
                    "outgoing_edge_ids": outgoing_edges,
                    "incoming_lane_count": len(incoming_lanes),
                },
            )
        )

    for zone in map_config.get("pickup_zones") or []:
        zone_id = str(zone.get("id") or "")
        zone_name = str(zone.get("name") or zone_id)
        edge_id = str(zone.get("edge_id") or "")
        lane_id = str(zone.get("lane_id") or "")
        objects.append(
            NetworkObject(
                object_type="pickup_zone",
                object_id=zone_id,
                display_name=zone_name,
                edge_id=edge_id,
                lane_id=lane_id,
                aliases=(zone_id, zone_name, edge_id, lane_id),
                attributes={
                    "description": zone.get("description", ""),
                    "capacity": zone.get("capacity"),
                    "boarding_duration_s": zone.get("boarding_duration_s"),
                    "start_pos": zone.get("start_pos"),
                    "end_pos": zone.get("end_pos"),
                },
            )
        )

    return {
        "objects": tuple(objects),
        "edges_by_id": edges_by_id,
        "lanes_by_edge": lanes_by_edge,
        "signal_controller_count": len(
            {element.get("id") for element in root.findall("tlLogic") if element.get("id")}
        ),
        "signal_program_count": len(root.findall("tlLogic")),
    }


def _score_object(query: str, item: NetworkObject, requested_type: str | None) -> int:
    score = 0
    object_id = _normalize(item.object_id)
    if object_id and object_id in query:
        score += 120
    for alias in item.aliases:
        normalized_alias = _normalize(alias)
        if not normalized_alias or len(normalized_alias) < 2:
            continue
        if normalized_alias == query:
            score = max(score, 110)
        elif normalized_alias in query:
            # Longer matching phrases carry the direction/movement semantics that
            # distinguish sibling lanes on the same approach.
            score = max(score, 45 + min(len(normalized_alias) * 3, 60))
        elif query in normalized_alias and len(query) >= 3:
            score = max(score, 35 + min(len(query), 20))
        else:
            score += _character_overlap_score(query, normalized_alias)
    if requested_type:
        score += 24 if item.object_type == requested_type else -10
    return score


def _character_overlap_score(query: str, alias: str) -> int:
    chunks = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_#.-]{2,}", query))
    score = 0
    for chunk in chunks:
        if chunk in alias:
            score += min(len(chunk) * 2, 18)
    return score


def _format_attribute_rows(item: NetworkObject) -> list[tuple[str, str]]:
    attrs = item.attributes
    rows: list[tuple[str, str]] = []
    if item.edge_id and item.object_type != "road":
        rows.append(("所属道路", f"`{item.edge_id}`"))
    if item.lane_id and item.object_type != "lane":
        rows.append(("绑定车道", f"`{item.lane_id}`"))
    mappings = (
        ("lane_count", "车道数", lambda value: f"{value} 条"),
        ("lane_index", "车道序号", lambda value: f"第 {int(value) + 1} 条"),
        ("movement_label", "转向属性", str),
        ("length_m", "长度", lambda value: f"{float(value):.1f} m"),
        ("speed_limit_mps", "限速", lambda value: f"{float(value):.2f} m/s（{float(value) * 3.6:.1f} km/h）"),
        ("width_m", "宽度", lambda value: f"{float(value):.1f} m" if float(value) > 0 else "未设置"),
        ("allow", "允许车型", lambda value: value or "采用默认允许规则"),
        ("disallow", "禁止车型", lambda value: value or "未单独设置"),
        ("junction_type", "路口类型", str),
        ("incoming_lane_count", "进口车道数", lambda value: f"{value} 条"),
        ("capacity", "容量", lambda value: f"{value} 辆"),
        ("boarding_duration_s", "单车停靠时间", lambda value: f"{value} 秒"),
        ("description", "说明", str),
    )
    for key, label, formatter in mappings:
        value = attrs.get(key)
        if value not in (None, "", []):
            rows.append((label, formatter(value)))
    return rows


def _build_spatial_selection(
    scenario_id: str,
    item: NetworkObject,
    lanes_by_edge: dict[str, list[NetworkObject]],
) -> dict[str, Any]:
    if item.object_type == "junction" or not item.edge_id:
        return {}
    lanes = lanes_by_edge.get(item.edge_id, [])
    lane_ids = [lane.lane_id for lane in lanes]
    lane_id = item.lane_id or (lane_ids[0] if lane_ids else "")
    selector_prefix = "zone" if item.object_type == "pickup_zone" else "edge"
    selector_value = item.object_id if item.object_type == "pickup_zone" else item.edge_id
    return {
        "scenario_id": scenario_id,
        "selector_key": f"{selector_prefix}:{selector_value}",
        "object_type": item.object_type if item.object_type == "pickup_zone" else "road",
        "display_name": item.display_name,
        "edge_id": item.edge_id,
        "lane_id": lane_id,
        "lane_ids": lane_ids,
    }


def _requested_list_type(text: str) -> str | None:
    if not any(word in text for word in LIST_WORDS):
        return None
    if "上客区" in text or "停车区" in text:
        return "pickup_zone"
    if "车道" in text:
        return "lane"
    if "路口" in text or "交叉口" in text:
        return "junction"
    if "道路" in text or "路段" in text:
        return "road"
    return None


def _requested_object_type(text: str) -> str | None:
    if "上客区" in text or "停车区" in text:
        return "pickup_zone"
    if "车道" in text:
        return "lane"
    if "路口" in text or "交叉口" in text:
        return "junction"
    if "道路" in text or "路段" in text or "进口" in text:
        return "road"
    return None


def _query_kind(text: str) -> str:
    if any(word in text for word in METRIC_WORDS):
        return "metrics"
    if any(word in text for word in ("连接", "相邻", "上游", "下游", "通向")):
        return "connectivity"
    return "detail"


def _looks_like_edge_impact_query(text: str) -> bool:
    has_road_scope = any(word in text for word in ("道路", "路段", "路网"))
    has_impact_scope = any(
        word in text
        for word in (
            "影响最大",
            "受影响",
            "影响排名",
            "流量增长最大",
            "速度下降最大",
            "时间损失最大",
            "压力最大",
            "热力图",
        )
    )
    return has_road_scope and has_impact_scope


def _looks_like_scene_overview(text: str) -> bool:
    has_overview = any(word in text for word in ("场景概况", "场景信息", "路网概况", "路网统计"))
    has_query = any(word in text for word in ("查询", "查看", "显示", "告诉我", "有哪些", "多少"))
    has_simulation_action = any(word in text for word in SIMULATION_ACTION_WORDS)
    return has_overview and has_query and not has_simulation_action


def _movement_label(scenario_id: str, lane_index: int, lane_count: int) -> str:
    if scenario_id.startswith("four_intersections") and lane_count >= 3:
        return {0: "左转", 1: "直行", 2: "右转"}.get(lane_index, "")
    return ""


def _deduplicate_candidates(objects: list[NetworkObject]) -> list[NetworkObject]:
    seen: set[tuple[str, str]] = set()
    result = []
    for item in objects:
        key = (item.object_type, item.object_id)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _has_exact_identifier(query: str, item: NetworkObject) -> bool:
    normalized = _normalize(query)
    return any(
        value and _normalize(value) in normalized
        for value in (item.object_id, item.edge_id, item.lane_id)
    )


def _clean_user_text(text: str) -> str:
    marker = "SimTrend空间精确定位"
    return text.split(marker, 1)[0].strip()


def _normalize(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff#.-]+", "", str(value).lower())


def _contains_object_id(text: str) -> bool:
    return bool(re.search(r"[a-z0-9]+(?:[_#.-][a-z0-9]+)+", text, flags=re.I))


def _to_float(value: str | None) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
