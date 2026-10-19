import pytest

from simtrend_app import integration as api
from simtrend_app.incident_drafts import prepare_incident_draft


def complete_fields():
    return {"edge_id": "e0_c10", "lane_id": "e0_c10_1", "incident_type": "追尾事故",
            "incident_duration_minutes": 10, "lane_closure_count": 1,
            "objective": "优先缓解排队", "duration_seconds": 600}


def test_draft_never_creates_a_simulation_job(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("a draft must not create or execute jobs")
    monkeypatch.setattr(api, "create_job", forbidden)
    monkeypatch.setattr(api, "submit", forbidden)
    result = api.bridge({"action": "incident_draft", "scenario_id": "four_intersections",
                         "fields": complete_fields(), "base_revision": 4})
    assert result["ready"] is True
    assert result["simulation_started"] is False
    assert result["base_revision"] == 4
    assert result["form"]["duration_seconds"] == 600
    assert result["selection"]["lane_id"] == "e0_c10_1"


def test_missing_fields_remain_unknown_and_do_not_inherit_defaults():
    result = prepare_incident_draft("four_intersections", {"edge_id": "e0_c10", "incident_type": "追尾事故"})
    assert result["ready"] is False
    assert result["form"]["duration_seconds"] is None
    assert result["form"]["lane_closure_count"] is None
    assert "事故车道" in result["missing_fields"]
    assert "仿真时长" in result["missing_fields"]


@pytest.mark.parametrize("patch", [
    {"lane_id": "w0_c00_0"}, {"edge_id": "not-a-road"}, {"zone_id": "unknown"},
    {"lane_closure_count": 4}, {"duration_seconds": 10}, {"duration_seconds": 600.5},
    {"lane_closure_count": True}, {"incident_type": "unknown"}, {"arbitrary": "field"},
])
def test_draft_rejects_invalid_or_inconsistent_parameters(patch):
    with pytest.raises(ValueError):
        prepare_incident_draft("four_intersections", {**complete_fields(), **patch})


def test_short_run_warns_without_claiming_full_incident_coverage():
    result = prepare_incident_draft("four_intersections", {**complete_fields(), "duration_seconds": 60})
    assert result["ready"] is True
    assert result["warnings"]


def test_confirmation_uses_the_same_validated_values():
    body = {"task": "incident", "scenario_id": "four_intersections", "draft_mode": True,
            "selection": {"edge_id": "e0_c10", "lane_id": "e0_c10_1"},
            "form": {key: value for key, value in complete_fields().items() if key not in {"edge_id", "lane_id"}}}
    tool, arguments = api.prepare_form(body)
    assert tool == "run_incident_signal_optimization"
    assert arguments["duration_seconds"] == 600
    assert "地图车道ID：e0_c10_1" in arguments["incident_text"]
    assert "持续10分钟" in arguments["incident_text"]
    body["form"].pop("duration_seconds")
    with pytest.raises(ValueError, match="仿真时长"):
        api.prepare_form(body)
