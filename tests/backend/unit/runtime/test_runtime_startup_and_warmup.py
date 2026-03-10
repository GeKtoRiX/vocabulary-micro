from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.bootstrap.initialization_coordinator import InitializationCoordinator
from infrastructure.config.env_readers import read_bool, read_float, read_int, read_str


def test_env_readers_parse_values_and_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOL_ON", " yes ")
    monkeypatch.setenv("BOOL_OFF", "no")
    monkeypatch.setenv("INT_OK", "42")
    monkeypatch.setenv("INT_BAD", "4x")
    monkeypatch.setenv("FLOAT_OK", "3.5")
    monkeypatch.setenv("FLOAT_BAD", "x")
    monkeypatch.setenv("STR_VAL", "raw-value")
    monkeypatch.delenv("NOT_SET", raising=False)

    assert read_bool("BOOL_ON", default=False) is True
    assert read_bool("BOOL_OFF", default=True) is False
    assert read_bool("NOT_SET", default=True) is True
    assert read_int("INT_OK", default=0) == 42
    assert read_int("INT_BAD", default=7) == 7
    assert read_int("NOT_SET", default=9) == 9
    assert read_float("FLOAT_OK", default=0.0) == pytest.approx(3.5)
    assert read_float("FLOAT_BAD", default=1.25) == pytest.approx(1.25)
    assert read_float("NOT_SET", default=2.5) == pytest.approx(2.5)
    assert read_str("STR_VAL", default="x") == "raw-value"
    assert read_str("NOT_SET", default="fallback") == "fallback"


def test_initialization_coordinator_start_wait_and_snapshot_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = InitializationCoordinator(
        project_root=tmp_path,
        db_path=tmp_path / "lexicon.sqlite3",
    )
    monkeypatch.setattr(coordinator, "_warmup_semantic_engine", lambda: None)

    assert coordinator.wait(timeout_seconds=0.01) is True
    assert coordinator.start() is True
    assert coordinator.start() is False
    assert coordinator.wait(timeout_seconds=1.0) is True

    snapshot = coordinator.snapshot()
    assert snapshot.ready is True
    assert snapshot.failed is False
    assert snapshot.running is False
    assert snapshot.started_at is not None
    assert snapshot.finished_at is not None
    assert snapshot.error_message == ""


def test_initialization_coordinator_failure_sets_failed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = InitializationCoordinator(
        project_root=tmp_path,
        db_path=tmp_path / "lexicon.sqlite3",
    )

    def _fail() -> None:
        raise RuntimeError("warmup failed")

    monkeypatch.setattr(coordinator, "_warmup_semantic_engine", _fail)
    assert coordinator.start() is True
    assert coordinator.wait(timeout_seconds=1.0) is True

    snapshot = coordinator.snapshot()
    assert snapshot.ready is False
    assert snapshot.failed is True
    assert snapshot.running is False
    assert "warmup failed" in snapshot.error_message


def test_initialization_coordinator_wait_false_when_thread_alive(tmp_path: Path) -> None:
    coordinator = InitializationCoordinator(project_root=tmp_path, db_path=tmp_path / "db.sqlite3")

    class _FakeThread:
        def join(self, timeout: float | None = None) -> None:
            _ = timeout

        def is_alive(self) -> bool:
            return True

    coordinator._thread = _FakeThread()  # type: ignore[assignment]
    assert coordinator.wait(timeout_seconds=0.0) is False
