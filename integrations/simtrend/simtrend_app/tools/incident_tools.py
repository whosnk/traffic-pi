from __future__ import annotations

from simtrend_app.tools.base import ToolResult


def analyze_incident(incident_text: str) -> ToolResult:
    keywords = ["事故", "拥堵", "追尾", "congestion", "incident", "queue"]
    matched = [word for word in keywords if word in incident_text.lower() or word in incident_text]

    if matched:
        return ToolResult(
            ok=True,
            message=f"已识别到交通事件关键词：{', '.join(matched)}。",
            data={"incident_level": "medium", "matched_keywords": matched},
        )

    return ToolResult(
        ok=True,
        message="暂未识别到明显交通事件关键词，但后续仍可继续进行仿真。",
        data={"incident_level": "low", "matched_keywords": []},
    )
