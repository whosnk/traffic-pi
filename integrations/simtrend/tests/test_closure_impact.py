from pathlib import Path

from simtrend_app.closure_impact import analyze_closure_impact


SCENARIO_PATH = Path("simtrend_scenarios/four_intersections")
ROUTE_FILE = SCENARIO_PATH / "routes" / "intersection.rou.xml"
NET_FILE = SCENARIO_PATH / "network" / "intersection.net.xml"


def _incident_context() -> dict:
    return {
        "apply_scene_edit": True,
        "incident_duration_minutes": 10,
        "blocked_lane_id": "c00_w0_0",
        "closed_lane_ids": ["c00_w0_0"],
        "blocked_edge_id": "c00_w0",
    }


def test_precheck_identifies_and_removes_route_blocked_for_full_run() -> None:
    result = analyze_closure_impact(
        ROUTE_FILE,
        NET_FILE,
        _incident_context(),
        duration_seconds=600,
    )

    assert result["enabled"]
    assert result["requires_mitigation"]
    assert result["simulation_can_proceed"]
    assert result["handling_mode"] == "remove_during_closure"
    assert result["affected_route_ids"] == ["n0_right"]
    assert result["affected_flow_ids"] == ["flow_n0_right"]
    assert result["removed_flow_ids"] == ["flow_n0_right"]
    assert result["delayed_flow_ids"] == []


def test_precheck_normalizes_mismatched_incident_overlay_route() -> None:
    incident_context = _incident_context()
    incident_context["route_edges"] = "e0_c10 c10_c00"

    result = analyze_closure_impact(
        ROUTE_FILE,
        NET_FILE,
        incident_context,
        duration_seconds=600,
    )

    assert not result["overlay_route_consistent"]
    assert result["overlay_route_normalized"]
    assert result["effective_overlay_route_edges"] == ["c00_w0"]
    assert "自动归一化" in result["note"]


def test_precheck_delays_blocked_flow_when_lane_reopens_during_run() -> None:
    result = analyze_closure_impact(
        ROUTE_FILE,
        NET_FILE,
        _incident_context(),
        duration_seconds=900,
    )

    assert result["closure_end_s"] == 600
    assert result["handling_mode"] == "delay_until_reopen"
    assert result["removed_flow_ids"] == []
    assert result["delayed_flow_ids"] == ["flow_n0_right"]


def test_precheck_is_a_safe_noop_without_lane_closure() -> None:
    result = analyze_closure_impact(
        ROUTE_FILE,
        NET_FILE,
        {},
        duration_seconds=600,
    )

    assert not result["enabled"]
    assert not result["requires_mitigation"]
    assert result["simulation_can_proceed"]
    assert result["handling_mode"] == "no_action"
