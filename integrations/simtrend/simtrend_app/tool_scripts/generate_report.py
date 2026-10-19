from __future__ import annotations

import argparse

from simtrend_app.tool_scripts.common import load_json, save_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a human-readable report payload from tool-chain outputs.")
    parser.add_argument("--detection-json", required=True)
    parser.add_argument("--signal-plan-json", required=True)
    parser.add_argument("--comparison-json", required=True)
    parser.add_argument("--closure-analysis-json", required=True)
    parser.add_argument("--strategy", default="signal_optimization")
    parser.add_argument("--scenario", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    detection = load_json(args.detection_json)
    signal_plan_payload = load_json(args.signal_plan_json)
    comparison_payload = load_json(args.comparison_json)
    closure_analysis_payload = load_json(args.closure_analysis_json)
    closure_precheck = closure_analysis_payload.get("closure_precheck", {})
    target_plan = detection["target_plan"]
    incident_context = signal_plan_payload.get("incident_context", {})
    incident_impacts = comparison_payload.get("incident_impacts", {})
    baseline_impact = incident_impacts.get("baseline", {})
    pickup_waiting = comparison_payload.get("pickup_waiting", {})
    baseline_pickup = pickup_waiting.get("baseline", {})
    demand_adjustments = comparison_payload.get("demand_adjustments", {})
    baseline_demand = demand_adjustments.get("baseline", {})

    detail_parts = [
        f"重点对象：{target_plan['target_label']}",
        f"优化轴向：{target_plan['axis_label']}",
        f"优化策略：{args.strategy}",
        f"仿真时长：{signal_plan_payload['duration_seconds']} 秒",
    ]
    if args.scenario:
        detail_parts.append(f"场景：{args.scenario}")
    if baseline_demand:
        vehicle_summary = ""
        if baseline_demand.get("vehicle_demand_enabled"):
            vehicle_summary = (
                f"，车辆 {baseline_demand.get('original_vehicle_count', 0)}"
                f" -> {baseline_demand.get('adjusted_vehicle_count', 0)} 辆"
            )
        detail_parts.append(
            "交通需求强度："
            f"{baseline_demand.get('profile_label', '标准流量')}"
            f"（倍率 {float(baseline_demand.get('multiplier', 1.0)):.2f}，"
            f"缩放车流 {baseline_demand.get('scaled_flow_count', 0)} 条"
            f"{vehicle_summary}）"
        )
    if incident_context.get("apply_scene_edit"):
        detail_parts.append(
            "事故场景注入："
            f"{incident_context.get('blocked_lane_label', '目标进口')}"
            f" 封闭 {incident_context.get('lane_closure_count', 0)} 条车道，"
            f"持续 {incident_context.get('incident_duration_minutes', 0)} 分钟"
        )
    if closure_precheck.get("enabled"):
        detail_parts.append(
            "封道影响预检："
            f"影响路线 {len(closure_precheck.get('affected_route_ids', []))} 条，"
            f"计划移除车流 {len(closure_precheck.get('removed_flow_ids', []))} 条，"
            f"计划延后车流 {len(closure_precheck.get('delayed_flow_ids', []))} 条"
        )
    if any(
        baseline_impact.get(key)
        for key in ("removed_flow_ids", "delayed_flow_ids", "removed_vehicle_ids", "delayed_vehicle_ids")
    ):
        detail_parts.append(
            "封道可行性处理："
            f"受阻转向 {len(baseline_impact.get('affected_route_ids', []))} 条，"
            f"移除事故期车流 {len(baseline_impact.get('removed_flow_ids', []))} 条，"
            f"延后恢复车流 {len(baseline_impact.get('delayed_flow_ids', []))} 条，"
            f"移除车辆 {len(baseline_impact.get('removed_vehicle_ids', []))} 辆，"
            f"延后车辆 {len(baseline_impact.get('delayed_vehicle_ids', []))} 辆"
        )
    if baseline_pickup.get("enabled"):
        zone_parts = []
        for zone in baseline_pickup.get("zones", []):
            zone_parts.append(
                f"{zone.get('name', zone.get('id', '上客区'))}"
                f" 容量 {zone.get('capacity', 0)} 泊位、"
                f"平均上客 {zone.get('boarding_duration_s', 0)} 秒、"
                f"插入停靠 {zone.get('matched_vehicle_count', 0)} 辆"
            )
        if zone_parts:
            detail_parts.append("网约车上客区停靠等待：" + "；".join(zone_parts))

    tool_chain_steps = [
        "detect_incident.py",
        "build_signal_plan.py",
        "analyze_closure_impact.py",
        "run_baseline_simulation.py",
        "run_optimized_simulation.py",
        "compare_metrics.py",
        "generate_report.py",
    ]

    human_message = (
        "已通过多工具链完成交通仿真分析。"
        + "；".join(detail_parts)
        + "。\n\n"
        + comparison_payload["comparison_summary"]
        + f"\n\n结论：{comparison_payload['tradeoff_note']}"
    )

    save_json(
        args.output,
        {
            "human_message": human_message,
            "tool_chain_steps": tool_chain_steps,
            "tradeoff_note": comparison_payload["tradeoff_note"],
            "incident_context": incident_context,
            "closure_precheck": closure_precheck,
            "incident_impacts": incident_impacts,
            "pickup_waiting": pickup_waiting,
            "demand_adjustments": demand_adjustments,
        },
    )


if __name__ == "__main__":
    main()
