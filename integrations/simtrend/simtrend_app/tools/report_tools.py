from __future__ import annotations

from simtrend_app.tools.base import ToolResult


def generate_report(incident_text: str) -> ToolResult:
    return ToolResult(
        ok=True,
        message=(
            "已生成一份占位版结果摘要。"
            f"当前请求内容：{incident_text}"
        ),
        data={"status": "draft_report_ready"},
    )
