import re

from simtrend_app.display_text import sanitize_display_text, sanitize_display_value


def test_display_text_hides_engine_implementation_names() -> None:
    source = (
        "SUMO-GUI 使用 SUMO_HOME 调用 sumo.exe，配置为 intersection.sumocfg，"
        "工具 run_sumo_demo。"
    )

    result = sanitize_display_text(source)

    assert not re.search("sumo", result, flags=re.IGNORECASE)
    assert "SimTrend" in result
    assert ".simtrendcfg" in result


def test_nested_process_payload_uses_display_safe_keys_and_values() -> None:
    payload = {
        "sumo_binary": "E:/sumo/bin/sumo.exe",
        "nested": [{"sumo_project_dir": "D:/sumo_project"}],
    }

    result = sanitize_display_value(payload)
    serialized = str(result)

    assert "simulation_engine" in result
    assert "simulation_project_dir" in result["nested"][0]
    assert not re.search("sumo", serialized, flags=re.IGNORECASE)
