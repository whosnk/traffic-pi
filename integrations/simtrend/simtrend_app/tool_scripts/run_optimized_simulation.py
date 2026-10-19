from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simtrend_app.edge_metrics import write_edge_data_additional
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.tool_scripts.common import (
    build_runtime_additional_files,
    build_output_paths,
    build_safe_runtime_route_plan,
    find_sumo_binary,
    load_pickup_zones,
    load_json,
    run_simulation,
    save_json,
    write_optimized_network,
    write_sumocfg,
)
from simtrend_app.tool_scripts.render_replay_gif import render_replay_gif


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the optimized SimTrend Engine simulation.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--signal-plan-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    runtime = ScenarioRuntime.from_project_dir(Path(args.project_dir).resolve())
    runtime.validate_required_files()
    project_dir = runtime.project_dir

    signal_plan_payload = load_json(args.signal_plan_json)
    duration = int(signal_plan_payload["duration_seconds"])
    signal_plan = signal_plan_payload["signal_plan"]
    incident_context = signal_plan_payload.get("incident_context", {})
    demand_profile = signal_plan_payload.get("demand_profile", {})

    base_net_file = runtime.net_file
    route_file = runtime.route_file
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    optimized_net_file = output_dir / "optimized_intersection.net.xml"
    optimized_cfg_file = output_dir / "optimized_intersection.sumocfg"
    write_optimized_network(base_net_file, optimized_net_file, signal_plan)

    pickup_zones = load_pickup_zones(project_dir)
    runtime_route_plan = build_safe_runtime_route_plan(
        route_file,
        optimized_net_file,
        output_dir,
        incident_context,
        duration,
        pickup_zones=pickup_zones,
        demand_profile=demand_profile,
    )
    runtime_route_files = runtime_route_plan["route_files"]
    incident_impact = runtime_route_plan["incident_impact"]
    pickup_waiting = runtime_route_plan["pickup_waiting"]
    demand_adjustment = runtime_route_plan["demand_adjustment"]
    runtime_additional_files = build_runtime_additional_files(
        output_dir,
        incident_context,
        duration,
        pickup_zones=pickup_zones,
    )
    edge_metrics_file = output_dir / "edge_metrics.xml"
    edge_metrics_additional = output_dir / "edge_metrics.add.xml"
    write_edge_data_additional(edge_metrics_additional, edge_metrics_file, duration)
    runtime_additional_files.append(edge_metrics_additional)
    write_sumocfg(
        optimized_cfg_file,
        optimized_net_file,
        runtime_route_files,
        duration,
        additional_files=runtime_additional_files,
    )

    sumo_binary = find_sumo_binary("sumo")
    outputs = build_output_paths(output_dir)
    replay_file = output_dir / "optimized_replay.gif"
    replay_file.unlink(missing_ok=True)
    run = run_simulation(
        label="优化方案 SimTrend 仿真",
        sumo_binary=sumo_binary,
        cfg_path=optimized_cfg_file,
        workdir=project_dir,
        duration=duration,
        outputs=outputs,
    )
    animation = {}
    if run["ok"]:
        animation = render_replay_gif(
            net_file=optimized_net_file,
            fcd_file=outputs["fcd"],
            output_file=replay_file,
            duration_seconds=duration,
            title="Optimized replay",
        )
    save_json(
        args.output,
        {
            "sumo_binary": sumo_binary,
            "scenario_runtime": runtime.as_dict(),
            "cfg_file": str(optimized_cfg_file),
            "net_file": str(optimized_net_file),
            "duration_seconds": duration,
            "incident_context": incident_context,
            "incident_impact": incident_impact,
            "pickup_waiting": pickup_waiting,
            "demand_profile": demand_profile,
            "demand_adjustment": demand_adjustment,
            "route_files": [str(path) for path in runtime_route_files],
            "additional_files": [str(path) for path in runtime_additional_files],
            "outputs": {key: str(value) for key, value in outputs.items()},
            "edge_metrics_file": str(edge_metrics_file),
            "animation": animation,
            "run": run,
        },
    )
    if not run["ok"]:
        sys.exit(run["returncode"] if isinstance(run["returncode"], int) else 1)


if __name__ == "__main__":
    main()
