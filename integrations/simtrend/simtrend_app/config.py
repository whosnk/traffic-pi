from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass(frozen=True)
class Settings:
    qwen_api_key: str
    qwen_base_url: str
    qwen_model: str
    sumo_project_dir: str
    debug: bool
    public_demo: bool
    single_visitor: bool
    visitor_lock_ttl_seconds: int

    @property
    def sumo_project_path(self) -> Path:
        return Path(self.sumo_project_dir).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    public_demo = _env_flag("APP_PUBLIC_DEMO", False)
    return Settings(
        qwen_api_key=(os.getenv("DEEPSEEK_API_KEY") or os.getenv("QWEN_API_KEY", "")).strip(),
        qwen_base_url=(
            os.getenv("DEEPSEEK_BASE_URL")
            or os.getenv("QWEN_BASE_URL")
            or "https://api.deepseek.com"
        ).rstrip("/"),
        qwen_model=(
            os.getenv("DEEPSEEK_MODEL")
            or os.getenv("QWEN_MODEL")
            or "deepseek-v4-flash"
        ).strip(),
        sumo_project_dir=os.getenv("SUMO_PROJECT_DIR", str(Path(__file__).resolve().parents[1] / "simtrend_scenarios" / "four_intersections")).strip(),
        debug=_env_flag("APP_DEBUG", False),
        public_demo=public_demo,
        single_visitor=_env_flag("APP_SINGLE_VISITOR", public_demo),
        visitor_lock_ttl_seconds=_env_int("APP_VISITOR_LOCK_TTL_SECONDS", 1800, minimum=60),
    )


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(int(value.strip()), minimum)
    except ValueError:
        return default
