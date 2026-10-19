from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.edge_metrics import write_edge_data_additional
from simtrend_app.tool_scripts.common import (
    build_output_paths,
    build_runtime_additional_files,
    build_safe_runtime_route_plan,
    find_sumo_binary,
    load_json,
    load_pickup_zones,
    run_simulation,
    save_json,
    write_sumocfg,
)
from simtrend_app.tool_scripts.render_replay_gif import render_replay_gif


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one side of a traffic demand impact evaluation.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--demand-plan-json", required=True)
    parser.add_argument("--variant", choices=("reference", "adjusted"), required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    runtime = ScenarioRuntime.from_project_dir(Path(args.project_dir).resolve())
    runtime.validate_required_files()
    plan = load_json(args.demand_plan_json)
    duration = int(plan["duration_seconds"])
    demand_profile = plan[f"{args.variant}_profile"]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pickup_zones = load_pickup_zones(runtime.project_dir)
    route_plan = build_safe_runtime_route_plan(
        runtime.route_file,
        runtime.net_file,
        output_dir,
        {},
        duration,
        pickup_zones=pickup_zones,
        demand_profile=demand_profile,
    )
    additional_files = build_runtime_additional_files(
        output_dir,
        {},
        duration,
        pickup_zones=pickup_zones,
    )
    edge_metrics_file = output_dir / "edge_metrics.xml"
    edge_metrics_additional = output_dir / "edge_metrics.add.xml"
    write_edge_data_additional(edge_metrics_additional, edge_metrics_file, duration)
    additional_files.append(edge_metrics_additional)
    cfg_file = output_dir / f"{args.variant}_demand.sumocfg"
    write_sumocfg(
        cfg_file,
        runtime.net_file,
        route_plan["route_files"],
        duration,
        additional_files=additional_files,
    )

    sumo_binary = find_sumo_binary("sumo")
    outputs = build_output_paths(output_dir)
    variant_label = "原始需求" if args.variant == "reference" else "调整后需求"
    run = run_simulation(
        label=f"{variant_label} SimTrend 仿真",
        sumo_binary=sumo_binary,
        cfg_path=cfg_file,
        workdir=runtime.project_dir,
        duration=duration,
        outputs=outputs,
    )
    animation = {}
    if run["ok"]:
        animation = render_replay_gif(
            net_file=runtime.net_file,
            fcd_file=outputs["fcd"],
            output_file=output_dir / f"{args.variant}_demand_replay.gif",
            duration_seconds=duration,
            title=f"{variant_label}回放",
        )

    save_json(
        args.output,
        {
            "workflow_type": "demand_impact_evaluation",
            "variant": args.variant,
            "variant_label": variant_label,
            "sumo_binary": sumo_binary,
            "scenario_runtime": runtime.as_dict(),
            "cfg_file": str(cfg_file),
            "duration_seconds": duration,
            "demand_profile": demand_profile,
            "demand_adjustment": route_plan["demand_adjustment"],
            "pickup_waiting": route_plan["pickup_waiting"],
            "route_files": [str(path) for path in route_plan["route_files"]],
            "additional_files": [str(path) for path in additional_files],
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
