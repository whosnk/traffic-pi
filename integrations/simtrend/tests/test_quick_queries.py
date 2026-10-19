from simtrend_app.quick_queries import build_quick_query_actions


def test_quick_queries_require_map_selection_only_for_object_specific_actions() -> None:
    actions = {item.key: item for item in build_quick_query_actions()}

    assert actions["scene_overview"].enabled
    assert actions["signal_scope"].enabled
    assert not actions["selected_object"].enabled
    assert not actions["signal_phases"].enabled


def test_quick_queries_adapt_to_selected_pickup_zone() -> None:
    actions = {
        item.key: item
        for item in build_quick_query_actions(
            {
                "object_type": "pickup_zone",
                "edge_id": "pickup_edge",
                "lane_id": "pickup_edge_0",
            }
        )
    }

    assert actions["selected_object"].enabled
    assert "上客区" in actions["selected_object"].prompt
    assert actions["signal_phases"].enabled
    assert "当前相位配置" in actions["signal_phases"].prompt
