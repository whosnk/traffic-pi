from __future__ import annotations

import argparse

from simtrend_app.tool_scripts.common import build_signal_plan, load_json, normalize_duration, save_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a baseline and optimized signal timing plan.")
    parser.add_argument("--detection-json", required=True)
    parser.add_argument("--strategy", default="signal_optimization")
    parser.add_argument("--duration-seconds", type=int, default=300)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    detection = load_json(args.detection_json)
    target_plan = detection["target_plan"]
    incident_context = detection.get("incident_context", {})
    demand_profile = detection.get("demand_profile", {})

    save_json(
        args.output,
        {
            "strategy": args.strategy,
            "duration_seconds": normalize_duration(args.duration_seconds),
            "signal_plan": build_signal_plan(target_plan["axis_key"]),
            "target_plan": target_plan,
            "incident_context": incident_context,
            "demand_profile": demand_profile,
        },
    )


if __name__ == "__main__":
    main()
