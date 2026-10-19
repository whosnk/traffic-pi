from __future__ import annotations

import argparse

from simtrend_app.tool_scripts.common import infer_demand_profile, infer_incident_context, infer_target_plan, save_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect traffic incident target direction and affected axis.")
    parser.add_argument("--incident-text", required=True)
    parser.add_argument("--scenario", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    detected_tags: list[str] = []
    if any(word in args.incident_text for word in ["事故", "追尾", "碰撞"]):
        detected_tags.append("incident")
    if any(word in args.incident_text for word in ["排队", "拥堵", "堵塞"]):
        detected_tags.append("queue")

    target_plan = infer_target_plan(args.incident_text, args.scenario or None)
    incident_context = infer_incident_context(args.incident_text, target_plan)
    demand_profile = infer_demand_profile(args.incident_text)

    save_json(
        args.output,
        {
            "incident_text": args.incident_text,
            "scenario": args.scenario or None,
            "target_plan": target_plan,
            "incident_context": incident_context,
            "demand_profile": demand_profile,
            "detected_tags": detected_tags,
        },
    )


if __name__ == "__main__":
    main()
