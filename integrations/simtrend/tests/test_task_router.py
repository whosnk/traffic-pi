from simtrend_app.agent.task_router import TaskRouter


def test_router_selects_network_query_without_simulation() -> None:
    route = TaskRouter().route("查询东北路口东进口直行车道的信息")

    assert route.task_type == "network_query"
    assert route.workflow == "network_knowledge_query"
    assert route.required_categories == ("network_query",)


def test_router_selects_network_query_for_scene_overview() -> None:
    route = TaskRouter().route("查询当前场景概况，包括道路、车道和信号控制器数量")

    assert route.task_type == "network_query"
    assert route.workflow == "network_knowledge_query"


def test_router_selects_signal_optimization_for_incident() -> None:
    route = TaskRouter().route(
        "东北路口东进口发生追尾事故，持续10分钟，封闭1条车道，请进行信号优化仿真"
    )

    assert route.task_type == "signal_optimization"
    assert route.workflow == "signal_optimization"
    assert "simulation" in route.required_categories


def test_router_identifies_demand_adjustment() -> None:
    route = TaskRouter().route("把南京南站网约车到站流量提高30%，运行仿真并进行对比")

    assert route.task_type == "demand_adjustment"
    assert route.workflow == "demand_impact_evaluation"


def test_router_keeps_resolved_query_from_capturing_next_simulation() -> None:
    memory = [
        {"task_type": "network_query", "awaiting_network_clarification": True},
        {"task_type": "network_query", "awaiting_network_clarification": False},
    ]

    route = TaskRouter().route("刚才选择的车道发生事故，请进行信号优化仿真", memory)

    assert route.task_type == "signal_optimization"
