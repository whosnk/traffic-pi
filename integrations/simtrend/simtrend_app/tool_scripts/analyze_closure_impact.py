from __future__ import annotations

import argparse
from pathlib import Path

from simtrend_app.closure_impact import analyze_closure_impact
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.tool_scripts.common import load_json, save_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight lane-closure impact before simulation.")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--signal-plan-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    runtime = ScenarioRuntime.from_project_dir(Path(args.project_dir).resolve())
    runtime.validate_required_files()
    signal_plan_payload = load_json(args.signal_plan_json)
    duration_seconds = int(signal_plan_payload["duration_seconds"])
    incident_context = signal_plan_payload.get("incident_context", {})
    precheck = analyze_closure_impact(
        runtime.route_file,
        runtime.net_file,
        incident_context,
        duration_seconds,
    )
    save_json(
        args.output,
        {
            "scenario_runtime": runtime.as_dict(),
            "duration_seconds": duration_seconds,
            "incident_context": incident_context,
            "closure_precheck": precheck,
        },
    )


if __name__ == "__main__":
    main()
