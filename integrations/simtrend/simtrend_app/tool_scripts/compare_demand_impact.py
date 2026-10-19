from __future__ import annotations

import argparse

from simtrend_app.edge_metrics import collect_edge_metrics, compare_edge_metrics
from simtrend_app.tool_scripts.common import (
    build_comparison,
    collect_metrics,
    load_json,
    load_xml_root,
    save_json,
)


TARGET_PREFIXES = {
    "ride_hailing_in": ["rh_in_"],
    "ride_hailing_out": ["rh_out_"],
    "ride_hailing_all": ["rh_in_", "rh_out_"],
    "background": ["bg_"],
    "all": [""],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare reference and adjusted demand simulations.")
    parser.add_argument("--demand-plan-json", required=True)
    parser.add_argument("--reference-json", required=True)
    parser.add_argument("--adjusted-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plan = load_json(args.demand_plan_json)
    reference = load_json(args.reference_json)
    adjusted = load_json(args.adjusted_json)
    prefixes = TARGET_PREFIXES.get(plan.get("target", "all"), [""])
    metric_scope = {"lane_ids": [], "route_prefixes": prefixes}
    reference_metrics = collect_metrics(reference["outputs"], metric_scope)
    adjusted_metrics = collect_metrics(adjusted["outputs"], metric_scope)
    reference_target_completed = _target_completed_count(reference["outputs"]["tripinfo"], prefixes)
    adjusted_target_completed = _target_completed_count(adjusted["outputs"]["tripinfo"], prefixes)
    reference_edge_metrics = collect_edge_metrics(reference["edge_metrics_file"])
    adjusted_edge_metrics = collect_edge_metrics(adjusted["edge_metrics_file"])
    edge_impacts = compare_edge_metrics(reference_edge_metrics, adjusted_edge_metrics)
    comparison = build_comparison(reference_metrics, adjusted_metrics)
    comparison.update(
        {
            "target_avg_duration_before_s": reference_metrics["target_avg_duration_s"],
            "target_avg_duration_after_s": adjusted_metrics["target_avg_duration_s"],
            "target_avg_duration_delta_s": round(
                adjusted_metrics["target_avg_duration_s"] - reference_metrics["target_avg_duration_s"], 2
            ),
            "target_completed_before": reference_target_completed,
            "target_completed_after": adjusted_target_completed,
            "target_completed_delta": round(
                adjusted_target_completed - reference_target_completed, 2
            ),
            "inserted_before": reference_metrics["inserted_vehicle_count"],
            "inserted_after": adjusted_metrics["inserted_vehicle_count"],
            "inserted_delta": round(
                adjusted_metrics["inserted_vehicle_count"] - reference_metrics["inserted_vehicle_count"], 2
            ),
        }
    )
    wait_delta = comparison["overall_avg_wait_delta_s"]
    arrival_delta = comparison["arrived_delta"]
    impact_note = (
        f"需求调整后全网平均等待变化 {wait_delta:+.2f} 秒，"
        f"仿真期内完成车辆数变化 {arrival_delta:+.0f} 辆。"
    )

    save_json(
        args.output,
        {
            "workflow_type": "demand_impact_evaluation",
            "demand_plan": plan,
            "reference_metrics": reference_metrics,
            "adjusted_metrics": adjusted_metrics,
            "demand_adjustments": {
                "reference": reference.get("demand_adjustment", {}),
                "adjusted": adjusted.get("demand_adjustment", {}),
            },
            "pickup_waiting": {
                "reference": reference.get("pickup_waiting", {}),
                "adjusted": adjusted.get("pickup_waiting", {}),
            },
            "comparison": comparison,
            "edge_impacts": edge_impacts,
            "edge_impact_summary": {
                "analyzed_edge_count": len(edge_impacts),
                "high_impact_edge_count": sum(1 for row in edge_impacts if row["impact_level"] == "高"),
                "top_affected_edges": edge_impacts[:10],
            },
            "impact_note": impact_note,
        },
    )


def _target_completed_count(tripinfo_file: str, prefixes: list[str]) -> float:
    root = load_xml_root(tripinfo_file)
    return float(
        sum(
            1
            for trip in root.findall("tripinfo")
            if any(trip.get("id", "").startswith(prefix) for prefix in prefixes)
            and float(trip.get("arrival", "-1") or -1) >= 0
        )
    )


if __name__ == "__main__":
    main()
