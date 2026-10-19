from simtrend_app.agent.workflow import AgentWorkflow
from simtrend_app.config import Settings


def _settings() -> Settings:
    return Settings(
        "",
        "https://api.example.invalid",
        "test-model",
        "simtrend_scenarios/four_intersections",
        False,
        False,
        False,
        1800,
    )


def test_web_workflow_does_not_inherit_location_for_explicit_new_task(monkeypatch) -> None:
    previous_memory = [
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

    def fail_if_constructed(*args, **kwargs):
        raise AssertionError("澄清完成前，网页版不应创建仿真工具链")

    monkeypatch.setattr("simtrend_app.agent.workflow.AgentToolChain", fail_if_constructed)
    result = AgentWorkflow(_settings()).handle_user_message(
        "开始一个新任务：四交叉口场景中，东进口发生追尾事故，请进行信号优化仿真",
        conversation_memory=previous_memory,
    )

    assert result.model_source_label == "澄清对话"
    assert result.session_memory_entry["awaiting_clarification"]
    assert "具体路口" in result.rendered_markdown
    assert "事故预计持续多久" in result.rendered_markdown
    assert "封闭了几条车道" in result.rendered_markdown
