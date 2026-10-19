from simtrend_app.workspace_views import (
    ANIMATION_VIEW,
    RESULT_VIEW,
    latest_visuals,
    preferred_workspace_view,
    split_latest_turn,
)


def test_latest_visuals_separates_result_charts_and_replays() -> None:
    messages = [
        {"role": "assistant", "charts": [{"type": "bar", "title": "旧结果"}]},
        {
            "role": "assistant",
            "charts": [
                {"type": "bar", "title": "新结果"},
                {"type": "replay_gif", "title": "新动画"},
            ],
        },
    ]

    assert [item["title"] for item in latest_visuals(messages, replay=False)] == ["新结果"]
    assert [item["title"] for item in latest_visuals(messages, replay=True)] == ["新动画"]


def test_preferred_workspace_view_prioritizes_result_charts() -> None:
    assert preferred_workspace_view([{"type": "replay_gif"}]) == ANIMATION_VIEW
    assert preferred_workspace_view([{"type": "replay_gif"}, {"type": "bar"}]) == RESULT_VIEW
    assert preferred_workspace_view([]) is None


def test_split_latest_turn_keeps_latest_exchange_visible() -> None:
    messages = [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
    ]

    earlier, latest = split_latest_turn(messages)

    assert [item["content"] for item in earlier] == ["第一问", "第一答"]
    assert [item["content"] for item in latest] == ["第二问", "第二答"]
