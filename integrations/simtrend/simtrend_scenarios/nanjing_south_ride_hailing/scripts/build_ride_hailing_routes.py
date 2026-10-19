from __future__ import annotations

import math
import os
import random
import subprocess
import json
import xml.etree.ElementTree as ET
from pathlib import Path


SCENARIO_DIR = Path(__file__).resolve().parents[1]
NET_FILE = SCENARIO_DIR / "network" / "intersection.net.xml"
PLAIN_EDGE_FILE = SCENARIO_DIR / "raw" / "plain.edg.xml"
TRIPS_FILE = SCENARIO_DIR / "routes" / "ride_hailing.trips.xml"
ROUTE_FILE = SCENARIO_DIR / "routes" / "intersection.rou.xml"

STATION_LON = 118.7985
STATION_LAT = 31.9688


def main() -> None:
    graph = load_directed_graph()
    station_edges, outer_edges = select_edges(graph)
    station_edges = ensure_pickup_zone_edges(station_edges)
    trips = build_trips(station_edges, outer_edges, graph)
    write_trips(trips)
    run_duarouter()


def select_edges(graph: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    root = ET.parse(PLAIN_EDGE_FILE).getroot()
    candidates: list[tuple[float, str]] = []
    outer: list[tuple[float, str]] = []
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if not edge_id or edge_id.startswith(":"):
            continue
        if edge_id not in graph:
            continue
        if _is_disallowed(edge):
            continue
        points = _edge_points(edge)
        if not points:
            continue
        distance = min(_geo_distance_m(lon, lat, STATION_LON, STATION_LAT) for lon, lat in points)
        if 180 <= distance <= 900:
            candidates.append((distance, edge_id))
        if 1450 <= distance <= 2600:
            outer.append((distance, edge_id))

    station_edges = [edge_id for _, edge_id in sorted(candidates)[:36]]
    outer_edges = [edge_id for _, edge_id in sorted(outer, reverse=True)[:90]]
    if len(station_edges) < 6 or len(outer_edges) < 12:
        raise RuntimeError("未找到足够的南京南站周边道路边，无法生成网约车专题车流。")
    return station_edges, outer_edges


def ensure_pickup_zone_edges(station_edges: list[str]) -> list[str]:
    """Keep configured pickup areas reachable when routes are regenerated."""
    scenario_file = SCENARIO_DIR / "scenario.json"
    if not scenario_file.exists():
        return station_edges
    scenario = json.loads(scenario_file.read_text(encoding="utf-8-sig"))
    pickup_edges = [
        str(zone.get("edge_id", "")).strip()
        for zone in scenario.get("map", {}).get("pickup_zones", [])
        if zone.get("edge_id")
    ]
    merged = list(station_edges)
    for edge_id in pickup_edges:
        if edge_id and edge_id not in merged:
            merged.insert(0, edge_id)
    return merged


def build_trips(station_edges: list[str], outer_edges: list[str], graph: dict[str, set[str]]) -> list[dict[str, str]]:
    rng = random.Random(20260524)
    trips: list[dict[str, str]] = []
    reachable_cache: dict[str, set[str]] = {}
    station_set = set(station_edges)
    outer_set = set(outer_edges)

    def reachable_from(edge_id: str) -> set[str]:
        if edge_id not in reachable_cache:
            reachable_cache[edge_id] = _reachable_edges(edge_id, graph)
        return reachable_cache[edge_id]

    background_pairs = [
        (src, sorted((reachable_from(src) & outer_set) - {src}))
        for src in outer_edges
    ]
    arrival_pairs = [
        (src, sorted(reachable_from(src) & station_set))
        for src in outer_edges
    ]
    departure_pairs = [
        (src, sorted(reachable_from(src) & outer_set))
        for src in station_edges
    ]
    background_pairs = [(src, dsts) for src, dsts in background_pairs if dsts]
    arrival_pairs = [(src, dsts) for src, dsts in arrival_pairs if dsts]
    departure_pairs = [(src, dsts) for src, dsts in departure_pairs if dsts]
    if len(background_pairs) < 6 or len(arrival_pairs) < 6 or len(departure_pairs) < 2:
        raise RuntimeError("可达 OD 边不足，无法生成稳定的南京南站网约车车流。")

    # Background traffic keeps the whole 4 km network alive.
    for index in range(260):
        src, destinations = rng.choice(background_pairs)
        dst = rng.choice(destinations)
        trips.append(_trip(f"bg_{index}", index * 6, src, dst, "background_car"))

    # Ride-hailing arrivals concentrate near the station pickup/dropoff area.
    for index in range(520):
        src, destinations = rng.choice(arrival_pairs)
        dst = rng.choice(destinations)
        depart = max(0, int(rng.gauss(540, 210)))
        trips.append(_trip(f"rh_in_{index}", depart, src, dst, "ride_hailing"))

    # Vehicles leaving the station make the pickup area visibly active.
    for index in range(260):
        src, destinations = rng.choice(departure_pairs)
        dst = rng.choice(destinations)
        depart = max(60, int(rng.gauss(760, 260)))
        trips.append(_trip(f"rh_out_{index}", depart, src, dst, "ride_hailing"))

    return sorted(trips, key=lambda item: (float(item["depart"]), item["id"]))


def load_directed_graph() -> dict[str, set[str]]:
    root = ET.parse(NET_FILE).getroot()
    graph: dict[str, set[str]] = {}
    for edge in root.findall("edge"):
        edge_id = edge.get("id", "")
        if edge_id and not edge_id.startswith(":") and not edge.get("function"):
            graph[edge_id] = set()
    for connection in root.findall("connection"):
        from_edge = connection.get("from", "")
        to_edge = connection.get("to", "")
        if from_edge in graph and to_edge in graph:
            graph[from_edge].add(to_edge)
    return graph


def _reachable_edges(start_edge: str, graph: dict[str, set[str]]) -> set[str]:
    seen = {start_edge}
    stack = [start_edge]
    while stack:
        current = stack.pop()
        for neighbor in graph.get(current, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return seen


def write_trips(trips: list[dict[str, str]]) -> None:
    TRIPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">',
        '    <vType id="background_car" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" width="1.8" minGap="2.5" maxSpeed="13.89" guiShape="passenger/sedan" color="0.25,0.45,0.85"/>',
        '    <vType id="ride_hailing" vClass="passenger" accel="2.6" decel="4.5" sigma="0.4" length="5" width="1.8" minGap="2.0" maxSpeed="13.89" guiShape="passenger/van" color="1.0,0.55,0.10"/>',
    ]
    for item in trips:
        lines.append(
            f'    <trip id="{item["id"]}" type="{item["type"]}" depart="{item["depart"]}" '
            f'from="{item["from"]}" to="{item["to"]}" departLane="best" departSpeed="max"/>'
        )
    lines.append("</routes>")
    lines.append("")
    TRIPS_FILE.write_text("\n".join(lines), encoding="utf-8")


def run_duarouter() -> None:
    repo_root = SCENARIO_DIR.parents[1]
    command = [
        find_sumo_binary("duarouter"),
        "-n",
        str(NET_FILE.relative_to(repo_root)),
        "-r",
        str(TRIPS_FILE.relative_to(repo_root)),
        "-o",
        str(ROUTE_FILE.relative_to(repo_root)),
        "--ignore-errors",
        "true",
        "--remove-loops",
        "true",
        "--no-step-log",
        "true",
    ]
    subprocess.run(command, cwd=repo_root, check=True)
    strip_generated_configuration_comment(ROUTE_FILE)
    alt_file = ROUTE_FILE.with_suffix(".rou.alt.xml")
    if alt_file.exists():
        strip_generated_configuration_comment(alt_file)


def strip_generated_configuration_comment(route_file: Path) -> None:
    text = route_file.read_text(encoding="utf-8")
    marker = "-->\n\n<routes"
    if marker not in text:
        return
    route_file.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n\n<routes' + text.split(marker, 1)[1],
        encoding="utf-8",
    )


def find_sumo_binary(name: str) -> str:
    sumo_home = os.environ.get("SUMO_HOME", "").strip()
    suffix = ".exe" if os.name == "nt" else ""
    if sumo_home:
        candidate = Path(sumo_home) / "bin" / f"{name}{suffix}"
        if candidate.exists():
            return str(candidate)
    return f"{name}{suffix}"


def _trip(trip_id: str, depart: int, src: str, dst: str, vehicle_type: str) -> dict[str, str]:
    return {
        "id": trip_id,
        "depart": f"{min(depart, 1795):.2f}",
        "from": src,
        "to": dst,
        "type": vehicle_type,
    }


def _is_disallowed(edge: ET.Element) -> bool:
    disallow = edge.get("disallow", "")
    allow = edge.get("allow", "")
    if allow and "passenger" not in allow and "taxi" not in allow:
        return True
    return "passenger" in disallow


def _edge_points(edge: ET.Element) -> list[tuple[float, float]]:
    shape = edge.get("shape", "")
    points: list[tuple[float, float]] = []
    if shape:
        for token in shape.split():
            lon_text, lat_text = token.split(",", 1)
            points.append((float(lon_text), float(lat_text)))
    return points


def _geo_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    mean_lat = math.radians((lat1 + lat2) / 2)
    dx = (lon1 - lon2) * 111_320 * math.cos(mean_lat)
    dy = (lat1 - lat2) * 110_540
    return math.hypot(dx, dy)


if __name__ == "__main__":
    main()
