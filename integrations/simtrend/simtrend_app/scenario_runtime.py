from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScenarioRuntime:
    scenario_id: str
    name: str
    project_dir: Path
    description: str = ""
    default_prompt: str = ""
    intersections: tuple[dict, ...] = field(default_factory=tuple)
    location_examples: tuple[str, ...] = field(default_factory=tuple)
    supported_capabilities: tuple[str, ...] = field(default_factory=tuple)
    map_config: dict = field(default_factory=dict)
    raw_config: dict = field(default_factory=dict)

    @classmethod
    def from_project_dir(
        cls,
        project_dir: str | Path,
        *,
        scenario_id: str | None = None,
    ) -> "ScenarioRuntime":
        root = Path(project_dir).resolve()
        scenario_file = root / "scenario.json"
        payload: dict[str, Any] = {}
        if scenario_file.exists():
            try:
                payload = json.loads(scenario_file.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                payload = {}
        return cls.from_payload(payload, root, scenario_id=scenario_id)

    @classmethod
    def from_scenario(cls, scenario: Any) -> "ScenarioRuntime":
        return cls(
            scenario_id=str(getattr(scenario, "id", "") or getattr(scenario, "path", "scenario")),
            name=str(getattr(scenario, "name", "") or getattr(scenario, "id", "仿真场景")),
            description=str(getattr(scenario, "description", "") or ""),
            project_dir=Path(getattr(scenario, "path")).resolve(),
            default_prompt=str(getattr(scenario, "default_prompt", "") or ""),
            intersections=tuple(getattr(scenario, "intersections", []) or []),
            location_examples=tuple(getattr(scenario, "location_examples", []) or []),
            supported_capabilities=tuple(getattr(scenario, "supported_capabilities", []) or []),
            map_config=dict(getattr(scenario, "map_config", {}) or {}),
            raw_config={},
        )

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        project_dir: Path,
        *,
        scenario_id: str | None = None,
    ) -> "ScenarioRuntime":
        return cls(
            scenario_id=str(scenario_id or payload.get("id") or project_dir.name),
            name=str(payload.get("name") or project_dir.name),
            description=str(payload.get("description") or ""),
            project_dir=project_dir.resolve(),
            default_prompt=str(payload.get("default_prompt") or ""),
            intersections=tuple(payload.get("intersections") or []),
            location_examples=tuple(payload.get("location_examples") or []),
            supported_capabilities=tuple(payload.get("supported_capabilities") or []),
            map_config=dict(payload.get("map") or {}),
            raw_config=dict(payload),
        )

    @property
    def scenario_file(self) -> Path:
        return self.project_dir / "scenario.json"

    @property
    def cfg_file(self) -> Path:
        return self.project_dir / "cfg" / "intersection.sumocfg"

    @property
    def net_file(self) -> Path:
        return self.project_dir / "network" / "intersection.net.xml"

    @property
    def route_file(self) -> Path:
        return self.project_dir / "routes" / "intersection.rou.xml"

    @property
    def train_script(self) -> Path:
        return self.project_dir / "train.py"

    @property
    def gui_script(self) -> Path:
        return self.project_dir / "run_gui.py"

    @property
    def build_net_script(self) -> Path:
        return self.project_dir / "scripts" / "build_net.py"

    @property
    def outputs_dir(self) -> Path:
        return self.project_dir / "outputs"

    @property
    def agent_runs_dir(self) -> Path:
        return self.outputs_dir / "agent_runs"

    @property
    def map_enabled(self) -> bool:
        return bool(self.map_config.get("enabled"))

    def has_capability(self, keyword: str) -> bool:
        normalized = keyword.lower()
        return any(normalized in capability.lower() for capability in self.supported_capabilities)

    def validate_required_files(self) -> None:
        required = [
            self.cfg_file,
            self.route_file,
            self.net_file,
            self.build_net_script,
            self.gui_script,
            self.train_script,
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError(f"SimTrend 场景缺少必要文件：{missing}")

    def create_run_root(self, *, reuse_latest: bool = False) -> Path:
        if reuse_latest:
            run_root = self.agent_runs_dir / "latest_run"
            if run_root.exists():
                try:
                    for child in run_root.iterdir():
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                except PermissionError:
                    run_root = self._timestamped_run_root()
        else:
            run_root = self._timestamped_run_root()
        run_root.mkdir(parents=True, exist_ok=True)
        return run_root

    def run_subdirs(self, run_root: Path) -> dict[str, Path]:
        return {
            "json": run_root / "json",
            "baseline": run_root / "baseline",
            "optimized": run_root / "optimized",
        }

    def output_paths(self, run_dir: Path) -> dict[str, Path]:
        return build_output_paths(run_dir)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "project_dir": str(self.project_dir),
            "cfg_file": str(self.cfg_file),
            "net_file": str(self.net_file),
            "route_file": str(self.route_file),
            "outputs_dir": str(self.outputs_dir),
            "agent_runs_dir": str(self.agent_runs_dir),
            "map_enabled": self.map_enabled,
            "supported_capabilities": list(self.supported_capabilities),
        }

    def _timestamped_run_root(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return self.agent_runs_dir / stamp


def build_output_paths(run_dir: Path) -> dict[str, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "tripinfo": run_dir / "tripinfo.xml",
        "queue": run_dir / "queue.xml",
        "statistics": run_dir / "statistics.xml",
        "summary": run_dir / "summary.xml",
        "fcd": run_dir / "fcd.xml",
    }
