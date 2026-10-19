from __future__ import annotations

import argparse

from simtrend_app.tool_scripts.common import load_json, save_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a traffic demand impact report.")
    parser.add_argument("--demand-plan-json", required=True)
    parser.add_argument("--comparison-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plan = load_json(args.demand_plan_json)
    result = load_json(args.comparison_json)
    comparison = result["comparison"]
    adjusted_profile = plan["adjusted_profile"]
    target_multiplier = float(
        adjusted_profile.get("target_multiplier", adjusted_profile.get("multiplier", 1.0)) or 1.0
    )
    scope = plan.get("adjustment_scope") or {}
    human_message = (
        "已完成交通需求影响评估。"
        f"评估对象：{plan['target_label']}；调整倍率：{target_multiplier:.2f}；"
        f"调整时段：{scope.get('time_window_start_s', 0)}-{scope.get('time_window_end_s', plan['duration_seconds'])} 秒；"
        f"空间范围：{scope.get('spatial_scope_label', '整个场景')}；"
        f"仿真时长：{plan['duration_seconds']} 秒。\n\n"
        f"{result['impact_note']}"
    )
    edge_summary = result.get("edge_impact_summary") or {}
    if edge_summary:
        human_message += (
            f" 已分析 {edge_summary.get('analyzed_edge_count', 0)} 条实际通行道路，"
            f"其中高影响道路 {edge_summary.get('high_impact_edge_count', 0)} 条。"
        )
    save_json(
        args.output,
        {
            "workflow_type": "demand_impact_evaluation",
            "human_message": human_message,
            "impact_note": result["impact_note"],
            "controlled_variables": plan["controlled_variables"],
            "changed_variable": plan["changed_variable"],
            "adjustment_scope": scope,
            "tool_chain_steps": [
                "build_demand_plan.py",
                "run_demand_simulation.py（原始需求）",
                "run_demand_simulation.py（调整后需求）",
                "compare_demand_impact.py",
                "generate_demand_report.py",
            ],
            "comparison": comparison,
            "edge_impact_summary": edge_summary,
        },
    )


if __name__ == "__main__":
    main()
