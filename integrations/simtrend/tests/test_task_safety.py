from simtrend_app.task_safety import (
    is_explicit_new_task,
    isolate_conversation_memory,
    looks_like_new_task,
    review_task_intent,
)


def _previous_incident_memory() -> list[dict]:
    return [
        {
            "awaiting_clarification": False,
            "parsed_intent": {
                "task_type": "signal_optimization",
                "incident_type": "rear_end",
                "incident_type_label": "追尾事故",
                "location_text": "东北路口东进口直行车道",
                "incident_duration_minutes": 10,
                "lane_closure_count": 1,
                "simulation_duration_seconds": 600,
            },
        }
    ]


def test_explicit_new_task_isolates_previous_memory() -> None:
    message = "开始一个新任务：东进口发生追尾事故，请进行信号优化仿真"

    assert is_explicit_new_task(message)
    assert looks_like_new_task(message)
    assert isolate_conversation_memory(message, _previous_incident_memory()) == []


def test_follow_up_keeps_previous_memory() -> None:
    message = "继续，把仿真时长改成900秒"

    assert not is_explicit_new_task(message)
    assert not looks_like_new_task(message)
    assert isolate_conversation_memory(message, _previous_incident_memory())


def test_follow_up_still_inherits_previous_task_context() -> None:
    review = review_task_intent(
        "补充：仿真时长改成900秒",
        _previous_incident_memory(),
        task_route={"task_type": "signal_optimization", "workflow": "signal_optimization"},
    )

    assert not review.requires_clarification
    assert review.intent.merged_intent["location_text"] == "东北路口东进口直行车道"
    assert review.intent.merged_intent["simulation_duration_seconds"] == 900
    assert "location_text" in review.intent.inherited_fields


def test_new_ambiguous_incident_requires_clarification_without_inheritance() -> None:
    review = review_task_intent(
        "开始一个新任务：四交叉口场景中，东进口发生追尾事故，请进行信号优化仿真",
        _previous_incident_memory(),
        task_route={"task_type": "signal_optimization", "workflow": "signal_optimization"},
    )

    assert review.requires_clarification
    assert "具体路口位置" in review.intent.missing_fields
    assert "事故持续时间" in review.intent.missing_fields
    assert "封闭车道数量" in review.intent.missing_fields
    assert review.intent.inherited_fields == []


def test_complete_incident_passes_shared_safety_review() -> None:
    review = review_task_intent(
        "东北路口东进口直行车道发生追尾事故，持续10分钟，封闭1条车道，仿真600秒",
        [],
        task_route={"task_type": "signal_optimization", "workflow": "signal_optimization"},
    )

    assert not review.requires_clarification
