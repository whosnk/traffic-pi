from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from pathlib import Path


SCENARIO_DIR = Path(__file__).resolve().parents[1]
NET_FILE = SCENARIO_DIR / "network" / "intersection.net.xml"
REPORT_FILE = SCENARIO_DIR / "outputs" / "network_repair_audit.json"


def main() -> None:
    report = audit_network(NET_FILE)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


def audit_network(net_file: str | Path) -> dict:
    root = ET.parse(net_file).getroot()
    edges = _load_edges(root)
    incoming, outgoing = _load_connections(root, edges)
    components = _weak_components(edges, incoming, outgoing)
    main_component = set(components[0]) if components else set()
    leaf_edges = sorted(edge_id for edge_id in edges if not incoming[edge_id] or not outgoing[edge_id])
    abnormal_leaf_edges = [
        edge_id
        for edge_id in leaf_edges
        if edge_id not in main_component or _is_low_value_internal_type(edges[edge_id]["type"])
    ]
    boundary_portals = [
        edge_id
        for edge_id in leaf_edges
        if edge_id in main_component and edge_id not in abnormal_leaf_edges
    ]
    degraded_space_objects = [
        {
            "edge_id": edge_id,
            "type": data["type"],
            "reason": "非主连通块或非车辆主仿真道路，建议作为停车/步行/站区空间对象处理。",
        }
        for edge_id, data in edges.items()
        if edge_id not in main_component or _is_low_value_internal_type(data["type"])
    ]

    return {
        "summary": {
            "edge_count": len(edges),
            "weak_component_count": len(components),
            "largest_component_edge_count": len(main_component),
            "leaf_edge_count": len(leaf_edges),
            "abnormal_leaf_edge_count": len(abnormal_leaf_edges),
            "boundary_portal_count": len(boundary_portals),
            "degraded_space_object_count": len(degraded_space_objects),
        },
        "boundary_portals": boundary_portals,
        "abnormal_leaf_edges": abnormal_leaf_edges,
        "degraded_space_objects": degraded_space_objects,
    }


def _load_edges(root: ET.Element) -> dict[str, dict]:
    edges: dict[str, dict] = {}
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if not edge_id or edge_id.startswith(":") or edge.get("function"):
            continue
        lane = edge.find("lane")
        if lane is None:
            continue
        edges[edge_id] = {
            "type": edge.get("type", ""),
            "length": _to_float(lane.get("length"), 0.0),
        }
    return edges


def _load_connections(
    root: ET.Element,
    edges: dict[str, dict],
) -> tuple[defaultdict[str, set[str]], defaultdict[str, set[str]]]:
    incoming: defaultdict[str, set[str]] = defaultdict(set)
    outgoing: defaultdict[str, set[str]] = defaultdict(set)
    for edge_id in edges:
        incoming[edge_id]
        outgoing[edge_id]
    for connection in root.findall("connection"):
        from_edge = connection.get("from", "")
        to_edge = connection.get("to", "")
        if from_edge in edges and to_edge in edges:
            outgoing[from_edge].add(to_edge)
            incoming[to_edge].add(from_edge)
    return incoming, outgoing


def _weak_components(
    edges: dict[str, dict],
    incoming: defaultdict[str, set[str]],
    outgoing: defaultdict[str, set[str]],
) -> list[list[str]]:
    seen: set[str] = set()
    components: list[list[str]] = []
    for edge_id in edges:
        if edge_id in seen:
            continue
        queue: deque[str] = deque([edge_id])
        seen.add(edge_id)
        component: list[str] = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in incoming[current] | outgoing[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return sorted(components, key=len, reverse=True)


def _is_low_value_internal_type(edge_type: str) -> bool:
    return edge_type in {
        "highway.footway",
        "highway.pedestrian",
        "highway.cycleway",
        "highway.path",
        "highway.steps",
    }


def _to_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


if __name__ == "__main__":
    main()
