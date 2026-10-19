from __future__ import annotations

import os
import subprocess
from pathlib import Path


REMOVED_NON_VEHICLE_TYPES = ",".join(
    [
        "highway.footway",
        "highway.pedestrian",
        "highway.cycleway",
        "highway.path",
        "highway.steps",
    ]
)


def main() -> None:
    scenario_dir = Path(__file__).resolve().parents[1]
    repo_root = scenario_dir.parents[1]
    raw_osm = scenario_dir / "raw" / "nanjing_south.osm.xml"
    net_file = scenario_dir / "network" / "intersection.net.xml"
    plain_prefix = scenario_dir / "raw" / "plain"
    if not raw_osm.exists():
        raise FileNotFoundError(f"缺少 OSM 原始文件：{raw_osm}")

    command = [
        find_sumo_binary("netconvert"),
        "--osm-files",
        str(raw_osm.relative_to(repo_root)),
        "--output-file",
        str(net_file.relative_to(repo_root)),
        "--plain-output-prefix",
        str(plain_prefix.relative_to(repo_root)),
        "--tls.guess",
        "true",
        "--tls.join",
        "true",
        "--junctions.join",
        "true",
        "--junctions.join-dist",
        "15",
        "--remove-edges.isolated",
        "true",
        "--keep-edges.components",
        "1",
        "--remove-edges.by-type",
        REMOVED_NON_VEHICLE_TYPES,
        "--no-turnarounds.tls",
        "true",
        "--osm.turn-lanes",
        "true",
        "--osm.lane-access",
        "true",
        "--proj.utm",
        "true",
        "--proj.plain-geo",
        "true",
    ]
    subprocess.run(command, cwd=repo_root, check=True)


def find_sumo_binary(name: str) -> str:
    sumo_home = os.environ.get("SUMO_HOME", "").strip()
    suffix = ".exe" if os.name == "nt" else ""
    if sumo_home:
        candidate = Path(sumo_home) / "bin" / f"{name}{suffix}"
        if candidate.exists():
            return str(candidate)
    return f"{name}{suffix}"


if __name__ == "__main__":
    main()
