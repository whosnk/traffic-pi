from __future__ import annotations

import argparse

from simtrend_app.tool_scripts.common import (
    build_comparison,
    build_tradeoff_note,
    collect_metrics,
    format_comparison_summary,
    load_json,
    save_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare baseline and optimized simulation metrics.")
    parser.add_argument("--detection-json", required=True)
    parser.add_argument("--signal-plan-json", required=True)
    parser.add_argument("--baseline-json", required=True)
    parser.add_argument("--optimized-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    detection = load_json(args.detection_json)
    signal_plan_payload = load_json(args.signal_plan_json)
    baseline_result = load_json(args.baseline_json)
    optimized_result = load_json(args.optimized_json)

    failed_runs = [
        label
        for label, result in (("baseline", baseline_result), ("optimized", optimized_result))
        if not result.get("run", {}).get("ok")
    ]
    if failed_runs:
        raise RuntimeError(
            "Cannot compare failed simulations: " + ", ".join(failed_runs)
        )

    target_plan = detection["target_plan"]
    signal_plan = signal_plan_payload["signal_plan"]
    baseline_metrics = collect_metrics(baseline_result["outputs"], target_plan)
    optimized_metrics = collect_metrics(optimized_result["outputs"], target_plan)
    comparison = build_comparison(baseline_metrics, optimized_metrics)
    tradeoff_note = build_tradeoff_note(comparison, target_plan)

    save_json(
        args.output,
        {
            "target_plan": target_plan,
            "signal_plan": signal_plan,
            "baseline_metrics": baseline_metrics,
            "optimized_metrics": optimized_metrics,
            "incident_impacts": {
                "baseline": baseline_result.get("incident_impact", {}),
                "optimized": optimized_result.get("incident_impact", {}),
            },
            "pickup_waiting": {
                "baseline": baseline_result.get("pickup_waiting", {}),
                "optimized": optimized_result.get("pickup_waiting", {}),
            },
            "demand_adjustments": {
                "baseline": baseline_result.get("demand_adjustment", {}),
                "optimized": optimized_result.get("demand_adjustment", {}),
            },
            "comparison": comparison,
            "tradeoff_note": tradeoff_note,
            "comparison_summary": format_comparison_summary(comparison, signal_plan),
        },
    )


if __name__ == "__main__":
    main()
