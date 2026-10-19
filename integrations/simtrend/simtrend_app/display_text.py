from __future__ import annotations

import re
from typing import Any


_EXACT_KEY_REPLACEMENTS = {
    "sumo_binary": "simulation_engine",
    "sumo_project_dir": "simulation_project_dir",
    "sumo_home": "simulation_engine_home",
}


def sanitize_display_text(value: str) -> str:
    text = str(value)
    text = re.sub(r"(?i)run_sumo_demo", "run_simtrend_demo", text)
    text = re.sub(r"(?i)sumo_project_dir", "simulation_project_dir", text)
    text = re.sub(r"(?i)sumo_binary", "simulation_engine", text)
    text = re.sub(r"(?i)sumo_home", "SIMTREND_ENGINE_HOME", text)
    text = re.sub(r"(?i)sumo-gui", "SimTrend 动画窗口", text)
    text = re.sub(r"(?i)\.sumocfg", ".simtrendcfg", text)
    text = re.sub(r"(?i)sumo_xy", "simtrend_xy", text)
    text = re.sub(r"(?i)sumo(?:\.exe)?", "SimTrend Engine", text)
    return text


def sanitize_display_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_display_text(value)
    if isinstance(value, dict):
        return {
            _sanitize_key(key): sanitize_display_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_display_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_display_value(item) for item in value)
    return value


def _sanitize_key(value: Any) -> str:
    key = str(value)
    replacement = _EXACT_KEY_REPLACEMENTS.get(key.lower())
    return replacement or sanitize_display_text(key)
