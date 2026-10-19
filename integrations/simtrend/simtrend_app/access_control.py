from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path


_LOCK_GUARD = threading.Lock()
_RUNTIME_DIR = Path(__file__).resolve().parents[1] / ".simtrend_runtime"
_LOCK_FILE = _RUNTIME_DIR / "visitor_lock.json"


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    owner_id: str
    active_owner_id: str
    last_seen_age_seconds: int
    wait_seconds: int


def acquire_single_visitor_access(owner_id: str, ttl_seconds: int) -> AccessDecision:
    now = time.time()
    with _LOCK_GUARD:
        lock = _read_lock()
        active_owner = str(lock.get("owner_id") or "")
        last_seen = _to_float(lock.get("last_seen"), 0.0)
        age = int(max(now - last_seen, 0)) if last_seen else ttl_seconds + 1

        if not active_owner or active_owner == owner_id or age > ttl_seconds:
            created_at = _to_float(lock.get("created_at"), now) if active_owner == owner_id else now
            _write_lock(
                {
                    "owner_id": owner_id,
                    "created_at": created_at,
                    "last_seen": now,
                }
            )
            return AccessDecision(
                allowed=True,
                owner_id=owner_id,
                active_owner_id=owner_id,
                last_seen_age_seconds=0,
                wait_seconds=0,
            )

        return AccessDecision(
            allowed=False,
            owner_id=owner_id,
            active_owner_id=active_owner,
            last_seen_age_seconds=age,
            wait_seconds=max(ttl_seconds - age, 1),
        )


def release_single_visitor_access(owner_id: str) -> None:
    with _LOCK_GUARD:
        lock = _read_lock()
        if str(lock.get("owner_id") or "") == owner_id and _LOCK_FILE.exists():
            _LOCK_FILE.unlink()


def _read_lock() -> dict:
    if not _LOCK_FILE.exists():
        return {}
    try:
        return json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_lock(payload: dict) -> None:
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = _LOCK_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_file.replace(_LOCK_FILE)


def _to_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
