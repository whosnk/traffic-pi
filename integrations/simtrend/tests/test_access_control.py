from pathlib import Path

from simtrend_app import access_control


def test_single_visitor_lock_blocks_second_owner(tmp_path: Path, monkeypatch) -> None:
    lock_file = tmp_path / "visitor_lock.json"
    monkeypatch.setattr(access_control, "_LOCK_FILE", lock_file)
    monkeypatch.setattr(access_control, "_RUNTIME_DIR", tmp_path)

    first = access_control.acquire_single_visitor_access("owner-a", ttl_seconds=60)
    second = access_control.acquire_single_visitor_access("owner-b", ttl_seconds=60)
    first_again = access_control.acquire_single_visitor_access("owner-a", ttl_seconds=60)

    assert first.allowed
    assert not second.allowed
    assert second.wait_seconds > 0
    assert first_again.allowed


def test_single_visitor_lock_can_be_released(tmp_path: Path, monkeypatch) -> None:
    lock_file = tmp_path / "visitor_lock.json"
    monkeypatch.setattr(access_control, "_LOCK_FILE", lock_file)
    monkeypatch.setattr(access_control, "_RUNTIME_DIR", tmp_path)

    assert access_control.acquire_single_visitor_access("owner-a", ttl_seconds=60).allowed
    access_control.release_single_visitor_access("owner-a")

    assert access_control.acquire_single_visitor_access("owner-b", ttl_seconds=60).allowed


def test_single_visitor_lock_expires(tmp_path: Path, monkeypatch) -> None:
    lock_file = tmp_path / "visitor_lock.json"
    monkeypatch.setattr(access_control, "_LOCK_FILE", lock_file)
    monkeypatch.setattr(access_control, "_RUNTIME_DIR", tmp_path)

    monkeypatch.setattr(access_control.time, "time", lambda: 1000.0)
    assert access_control.acquire_single_visitor_access("owner-a", ttl_seconds=60).allowed

    monkeypatch.setattr(access_control.time, "time", lambda: 1061.0)
    takeover = access_control.acquire_single_visitor_access("owner-b", ttl_seconds=60)

    assert takeover.allowed
