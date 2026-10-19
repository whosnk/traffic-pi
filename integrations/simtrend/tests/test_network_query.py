import json
from pathlib import Path

from simtrend_app.network_query import NetworkQueryService, looks_like_network_query
from simtrend_app.map_selector import build_spatial_context
from simtrend_app.scenario_runtime import ScenarioRuntime


SCENARIO_ROOT = Path("simtrend_scenarios")


def _service(scenario_id: str) -> NetworkQueryService:
    runtime = ScenarioRuntime.from_project_dir(SCENARIO_ROOT / scenario_id)
    return NetworkQueryService(runtime)


def test_network_query_intent_does_not_capture_simulation_request() -> None:
    assert looks_like_network_query("查询东北路口东进口直行车道的信息")
    assert looks_like_network_query("这条道路的下游连接是什么？")
    assert not looks_like_network_query("东北路口东进口发生事故，请进行信号优化仿真")
    assert not looks_like_network_query("网约车到站流量提高30%后，哪些路段受到的影响最大？")
    assert looks_like_network_query("刚才哪些路段受到的影响最大？")


def test_resolved_network_clarification_does_not_capture_next_simulation() -> None:
    memory = [
        {"task_type": "network_query", "awaiting_network_clarification": True},
        {"task_type": "network_query", "awaiting_network_clarification": False},
    ]

    assert not looks_like_network_query(
        "刚才选择的车道发生事故，请进行信号优化仿真",
        memory,
    )


def test_four_intersection_lane_query_returns_real_lane_and_selection() -> None:
    result = _service("four_intersections").query("查询东北路口东进口直行车道的信息")

    assert result.status == "matched"
    assert result.candidates[0]["lane_id"] == "e0_c10_1"
    assert result.spatial_selection["edge_id"] == "e0_c10"
    assert result.spatial_selection["lane_id"] == "e0_c10_1"
    assert "限速" in result.answer_markdown
    assert "连接关系" in result.answer_markdown


def test_four_intersection_query_lists_named_junctions() -> None:
    result = _service("four_intersections").query("当前场景有哪些路口？")

    assert result.status == "list"
    assert "共识别到 **4** 个路口" in result.answer_markdown
    assert "东北路口" in result.answer_markdown
    assert "西南路口" in result.answer_markdown
    assert "路口 e0" not in result.answer_markdown


def test_four_intersection_junction_list_word_uses_named_junctions() -> None:
    result = _service("four_intersections").query("路口列表和路网信息")

    assert result.status == "list"
    assert len(result.candidates) == 4


def test_four_intersection_junction_candidates_exclude_boundary_nodes() -> None:
    result = _service("four_intersections").query("东进口追尾事故相关路口与道路")

    assert result.status == "ambiguous"
    assert {item["object_id"] for item in result.candidates} == {"c00", "c01", "c10", "c11"}


def test_scene_overview_reads_real_network_object_counts() -> None:
    service = _service("four_intersections")

    result = service.query("查询当前场景概况，包括路口、道路、车道和信号控制器数量")

    assert result.status == "overview"
    assert result.query_kind == "scene_overview"
    assert "当前场景路网概况" in result.answer_markdown
    assert "| 场景命名重点区域/路口 | 4 |" in result.answer_markdown
    assert "路网节点（含边界节点）" in result.answer_markdown
    assert f"| 道路 | {len(service.index['edges_by_id'])} |" in result.answer_markdown
    assert "| 信号控制器 | 4 |" in result.answer_markdown


def test_network_query_uses_current_map_selection_for_follow_up() -> None:
    selection = {
        "scenario_id": "four_intersections",
        "object_type": "road",
        "display_name": "东北路口东进口",
        "edge_id": "e0_c10",
        "lane_id": "e0_c10_1",
        "lane_ids": ["e0_c10_0", "e0_c10_1", "e0_c10_2"],
    }
    query = "这条道路的下游连接是什么？\n\n" + build_spatial_context(selection)

    result = _service("four_intersections").query(query)

    assert result.status == "matched"
    assert result.query_kind == "connectivity"
    assert result.candidates[0]["edge_id"] == "e0_c10"
    assert "下游道路" in result.answer_markdown


def test_network_query_reads_latest_lane_metrics(tmp_path) -> None:
    service = _service("four_intersections")
    service.runtime = ScenarioRuntime.from_payload(
        {"id": "four_intersections", "name": "测试场景"},
        tmp_path,
    )
    optimized_dir = service.runtime.agent_runs_dir / "latest_run" / "optimized"
    optimized_dir.mkdir(parents=True)
    (optimized_dir / "fcd.xml").write_text(
        '<fcd-export><timestep time="0"><vehicle id="v0" lane="e0_c10_1" speed="10"/>'
        '</timestep><timestep time="1"><vehicle id="v0" lane="e0_c10_1" speed="8"/>'
        '</timestep></fcd-export>',
        encoding="utf-8",
    )
    (optimized_dir / "queue.xml").write_text(
        '<queue-export><data timestep="0"><lanes>'
        '<lane id="e0_c10_1" queueing_length="12" queueing_time="4"/>'
        '</lanes></data></queue-export>',
        encoding="utf-8",
    )

    result = service.query(
        "查询东北路口东进口直行车道最近一次仿真的速度和排队指标"
    )

    assert result.status == "matched"
    assert result.query_kind == "metrics"
    assert result.candidates[0]["lane_id"] == "e0_c10_1"
    assert "最近一次优化仿真指标" in result.answer_markdown
    assert "平均行驶速度" in result.answer_markdown
    assert "最大排队长度" in result.answer_markdown


def test_nanjing_pickup_zone_query_returns_capacity_and_map_target() -> None:
    result = _service("nanjing_south_ride_hailing").query(
        "查询南京南站北广场网约车上客区的信息"
    )

    assert result.status == "matched"
    assert result.candidates[0]["object_id"] == "north_plaza_pickup"
    assert result.spatial_selection["selector_key"] == "zone:north_plaza_pickup"
    assert result.spatial_selection["edge_id"] == "189391594#0"
    assert "12 辆" in result.answer_markdown


def test_network_query_clarification_selects_numbered_candidate() -> None:
    service = _service("nanjing_south_ride_hailing")
    candidate_objects = [
        item.as_candidate()
        for item in service.index["objects"]
        if item.object_type == "road"
    ][:2]
    memory = [
        {
            "awaiting_network_clarification": True,
            "network_query_candidates": candidate_objects,
        }
    ]

    result = service.query("第 2 个", conversation_memory=memory)

    assert result.status == "matched"
    assert result.candidates[0]["object_id"] == candidate_objects[1]["object_id"]


def test_network_query_lists_latest_demand_affected_edges(tmp_path) -> None:
    service = _service("nanjing_south_ride_hailing")
    edge_id = next(iter(service.index["edges_by_id"]))
    service.runtime = ScenarioRuntime.from_payload(
        {"id": "nanjing_south_ride_hailing", "name": "测试场景"},
        tmp_path,
    )
    comparison_file = service.runtime.agent_runs_dir / "latest_run" / "json" / "demand_comparison.json"
    comparison_file.parent.mkdir(parents=True)
    comparison_file.write_text(
        json.dumps(
            {
                "edge_impact_summary": {
                    "top_affected_edges": [
                        {
                            "edge_id": edge_id,
                            "impact_score": 72.5,
                            "vehicle_entered_delta": 8,
                            "mean_speed_delta_mps": -1.2,
                            "time_loss_delta_s": 30,
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = service.query("刚才哪些路段受到的影响最大？")

    assert result.status == "list"
    assert result.query_kind == "demand_edge_impact"
    assert edge_id in result.answer_markdown
    assert "72.5" in result.answer_markdown
