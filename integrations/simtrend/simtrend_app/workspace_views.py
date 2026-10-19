from __future__ import annotations


MAP_VIEW = "空间地图"
RESULT_VIEW = "结果图表"
ANIMATION_VIEW = "动画回放"
WORKSPACE_VIEWS = (MAP_VIEW, RESULT_VIEW, ANIMATION_VIEW)


def latest_visuals(messages: list[dict], *, replay: bool) -> list[dict]:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        charts = [
            chart
            for chart in message.get("charts", [])
            if (chart.get("type") == "replay_gif") == replay
        ]
        if charts:
            return charts
    return []


def preferred_workspace_view(charts: list[dict]) -> str | None:
    if any(chart.get("type") != "replay_gif" for chart in charts):
        return RESULT_VIEW
    if any(chart.get("type") == "replay_gif" for chart in charts):
        return ANIMATION_VIEW
    return None


def split_latest_turn(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    latest_user_index = next(
        (index for index in range(len(messages) - 1, -1, -1) if messages[index].get("role") == "user"),
        0,
    )
    return messages[:latest_user_index], messages[latest_user_index:]
