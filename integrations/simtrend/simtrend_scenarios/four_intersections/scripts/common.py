from __future__ import annotations

import os
import platform
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sumo_home() -> Path:
    value = os.environ.get("SUMO_HOME")
    if not value:
        raise EnvironmentError(
            "未检测到 SUMO_HOME。请先安装 SUMO，并设置环境变量 SUMO_HOME。"
        )
    return Path(value)


def find_sumo_binary(name: str) -> str:
    home = sumo_home()
    suffix = ".exe" if platform.system().lower().startswith("win") else ""
    candidate = home / "bin" / f"{name}{suffix}"
    if candidate.exists():
        return str(candidate)
    return f"{name}{suffix}"
