from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    description: str
    path: Path
    default_prompt: str
    intersections: list[dict]
    location_examples: list[str]
    supported_capabilities: list[str]
    map_config: dict
    demand_profiles: dict
    hidden: bool = False

    @property
    def project_dir(self) -> str:
        return str(self.path)

    def runtime(self):
        from simtrend_app.scenario_runtime import ScenarioRuntime

        return ScenarioRuntime.from_scenario(self)


def load_scenarios(root: str | Path = "simtrend_scenarios", *, include_hidden: bool = False) -> list[Scenario]:
    root_path = Path(root).resolve()
    if not root_path.exists():
        return []

    scenarios: list[Scenario] = []
    for scenario_file in sorted(root_path.glob("*/scenario.json")):
        try:
            payload = json.loads(scenario_file.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("hidden") and not include_hidden:
            continue
        scenarios.append(
            Scenario(
                id=str(payload.get("id") or scenario_file.parent.name),
                name=str(payload.get("name") or scenario_file.parent.name),
                description=str(payload.get("description") or ""),
                path=scenario_file.parent.resolve(),
                default_prompt=str(payload.get("default_prompt") or ""),
                intersections=list(payload.get("intersections") or []),
                location_examples=list(payload.get("location_examples") or []),
                supported_capabilities=list(payload.get("supported_capabilities") or []),
                map_config=dict(payload.get("map") or {}),
                demand_profiles=dict(payload.get("demand_profiles") or {}),
                hidden=bool(payload.get("hidden", False)),
            )
        )
    return scenarios


def default_scenario(scenarios: list[Scenario], fallback_project_dir: str) -> Scenario:
    if scenarios:
        return scenarios[0]
    fallback_path = Path(fallback_project_dir).resolve()
    return Scenario(
        id="legacy_project",
        name="默认仿真项目",
        description="来自 .env 的默认仿真项目目录。",
        path=fallback_path,
        default_prompt="东北路口东进口直行车道发生追尾事故，持续10分钟，封闭1条车道，请进行信号优化仿真",
        intersections=[],
        location_examples=[],
        supported_capabilities=[],
        map_config={},
        demand_profiles={},
        hidden=False,
    )
