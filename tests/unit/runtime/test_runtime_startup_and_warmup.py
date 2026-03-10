from __future__ import annotations

import builtins
from pathlib import Path
import sqlite3
import sys
import types

import pytest

from infrastructure.bootstrap import StartupService
from infrastructure.bootstrap.initialization_coordinator import InitializationCoordinator
from infrastructure.config.env_readers import read_bool, read_float, read_int, read_str


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def test_startup_initialize_creates_context_paths(tmp_path: Path) -> None:
    service = StartupService(project_root=tmp_path)
    context = service.initialize()

    assert service.project_root == tmp_path.resolve()
    assert context.project_root == tmp_path.resolve()
    assert context.logs_dir.exists()
    assert context.logs_dir == (tmp_path / "infrastructure" / "runtime" / "logs").resolve()
    assert context.db_path == (tmp_path / "infrastructure" / "persistence" / "data" / "lexicon.sqlite3").resolve()
    assert context.app_log_path.name == "app.log"
    assert context.startup_error_log_path.name == "startup_error.log"


def test_startup_apply_sql_migrations_applies_once(tmp_path: Path) -> None:
    service = StartupService(project_root=tmp_path)
    db_path = tmp_path / "lexicon.sqlite3"
    migrations_dir = tmp_path / "migrations"
    _write(
        migrations_dir / "001_add_marker.sql",
        (
            "CREATE TABLE IF NOT EXISTS migration_runs(name TEXT NOT NULL);\n"
            "INSERT INTO migration_runs(name) VALUES ('run-001');\n"
        ),
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE lexicon_entries(id INTEGER PRIMARY KEY, value TEXT)")
        conn.commit()

    service._migrations_dir = lambda: migrations_dir  # type: ignore[method-assign]
    service._apply_sql_migrations(db_path=db_path)
    service._apply_sql_migrations(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        applied = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
        runs = conn.execute("SELECT COUNT(*) FROM migration_runs").fetchone()
    assert applied is not None and applied[0] == 1
    assert runs is not None and runs[0] == 1


def test_startup_apply_sql_migrations_skips_when_lexicon_table_missing(tmp_path: Path) -> None:
    service = StartupService(project_root=tmp_path)
    db_path = tmp_path / "lexicon.sqlite3"
    migrations_dir = tmp_path / "migrations"
    _write(
        migrations_dir / "001_create_marker.sql",
        "CREATE TABLE marker(id INTEGER PRIMARY KEY);",
    )

    service._migrations_dir = lambda: migrations_dir  # type: ignore[method-assign]
    service._apply_sql_migrations(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        marker_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='marker'"
        ).fetchone()
    assert marker_exists is None


def test_startup_apply_sql_migrations_skips_when_migrations_dir_is_empty(tmp_path: Path) -> None:
    service = StartupService(project_root=tmp_path)
    db_path = tmp_path / "lexicon.sqlite3"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)

    service._migrations_dir = lambda: migrations_dir  # type: ignore[method-assign]
    service._apply_sql_migrations(db_path=db_path)
    assert not db_path.exists()


def test_startup_pipeline_probe_reports_ok_for_healthy_pipeline(tmp_path: Path) -> None:
    service = StartupService(project_root=tmp_path)
    calls: dict[str, object] = {}
    logs: list[tuple[str, str]] = []

    class _Repository:
        def pipeline_status(self) -> dict[str, object]:
            return {"spacy_available": True}

        def parse_text(self, text: str, request_id: str | None = None) -> dict[str, object]:
            calls["first_pass_text"] = text
            calls["first_pass_request_id"] = request_id
            return {"pipeline_status": "ok"}

        def parse_mwe_text(
            self,
            text: str,
            *,
            request_id: str | None = None,
            top_n: int = 3,
            enabled: bool | None = None,
        ) -> dict[str, object]:
            calls["second_pass_text"] = text
            calls["second_pass_request_id"] = request_id
            calls["second_pass_top_n"] = top_n
            calls["second_pass_enabled"] = enabled
            return {
                "status": "ok",
                "reason": "",
                "stage_statuses": [{"stage": "mwe_detect", "status": "ok", "reason": ""}],
                "model_info": {
                    "spacy_model_available": True,
                    "spacy_model_unavailable_reason": "",
                },
            }

    class _Logger:
        def info(self, message: str) -> None:
            logs.append(("info", message))

        def warning(self, message: str) -> None:
            logs.append(("warning", message))

        def error(self, message: str) -> None:
            logs.append(("error", message))

    report = service.probe_pipeline_on_startup(repository=_Repository(), logger=_Logger())
    assert report.ok is True
    assert report.status == "ok"
    assert report.reason == ""
    assert report.first_pass_status == "ok"
    assert report.second_pass_status == "ok"
    assert report.detect_status == "ok"
    assert report.trf_model_available is True
    assert calls["first_pass_request_id"] == "startup_pipeline_probe_first_pass"
    assert calls["second_pass_request_id"] == "startup_pipeline_probe_second_pass"
    assert calls["second_pass_top_n"] == 1
    assert calls["second_pass_enabled"] is True
    assert logs and logs[0][0] == "info"
    assert "status=ok" in logs[0][1]


def test_startup_pipeline_probe_reports_degraded_when_trf_unavailable(tmp_path: Path) -> None:
    service = StartupService(project_root=tmp_path)
    logs: list[tuple[str, str]] = []

    class _Repository:
        def pipeline_status(self) -> dict[str, object]:
            return {"spacy_available": False}

        def parse_text(self, text: str, request_id: str | None = None) -> dict[str, object]:
            return {"pipeline_status": "ok"}

        def parse_mwe_text(
            self,
            text: str,
            *,
            request_id: str | None = None,
            top_n: int = 3,
            enabled: bool | None = None,
        ) -> dict[str, object]:
            return {
                "status": "skipped",
                "reason": "spacy_model_load_failed",
                "stage_statuses": [
                    {
                        "stage": "mwe_detect",
                        "status": "skipped",
                        "reason": "spacy_model_load_failed",
                    }
                ],
                "model_info": {
                    "spacy_model_available": False,
                    "spacy_model_unavailable_reason": "spacy_model_load_failed",
                },
            }

    class _Logger:
        def info(self, message: str) -> None:
            logs.append(("info", message))

        def warning(self, message: str) -> None:
            logs.append(("warning", message))

        def error(self, message: str) -> None:
            logs.append(("error", message))

    report = service.probe_pipeline_on_startup(repository=_Repository(), logger=_Logger())
    assert report.ok is False
    assert report.status == "degraded"
    assert report.reason == "spacy_model_load_failed"
    assert report.second_pass_status == "skipped"
    assert report.detect_status == "skipped"
    assert report.trf_model_available is False
    assert logs and logs[0][0] == "warning"
    assert "status=degraded" in logs[0][1]


def test_startup_pipeline_probe_reports_failed_when_repository_raises(tmp_path: Path) -> None:
    service = StartupService(project_root=tmp_path)
    logs: list[tuple[str, str]] = []

    class _Repository:
        def pipeline_status(self) -> dict[str, object]:
            raise RuntimeError("probe exploded")

        def parse_text(self, text: str, request_id: str | None = None) -> dict[str, object]:
            _ = (text, request_id)
            return {}

        def parse_mwe_text(
            self,
            text: str,
            *,
            request_id: str | None = None,
            top_n: int = 3,
            enabled: bool | None = None,
        ) -> dict[str, object]:
            _ = (text, request_id, top_n, enabled)
            return {}

    class _Logger:
        def info(self, message: str) -> None:
            logs.append(("info", message))

        def warning(self, message: str) -> None:
            logs.append(("warning", message))

        def error(self, message: str) -> None:
            logs.append(("error", message))

    report = service.probe_pipeline_on_startup(repository=_Repository(), logger=_Logger())
    assert report.ok is False
    assert report.status == "failed"
    assert report.reason == "probe_exception"
    assert "probe exploded" in report.first_pass_error
    assert logs and logs[0][0] == "error"
    assert "status=failed" in logs[0][1]


def test_startup_error_handlers_write_log_and_report_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = StartupService(project_root=tmp_path)
    context = service.initialize(db_path=tmp_path / "data" / "lexicon.sqlite3")
    dialog_messages: list[str] = []
    monkeypatch.setattr(service, "_show_startup_error_dialog", lambda message: dialog_messages.append(message))

    service.handle_startup_import_error(context=context, error=ImportError("module missing"))
    service.handle_unexpected_startup_error(context=context, error=RuntimeError("unexpected"))

    stderr = capsys.readouterr().err
    log_text = context.startup_error_log_path.read_text(encoding="utf-8")
    assert "STARTUP IMPORT ERROR" in log_text
    assert "STARTUP ERROR" in log_text
    assert "module missing" in stderr
    assert "unexpected" in stderr
    assert len(dialog_messages) == 2


def test_startup_show_error_dialog_swallows_tk_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    service = StartupService(project_root=Path("."))
    real_import = builtins.__import__

    def _failing_import(name: str, *args: object, **kwargs: object):
        if name == "tkinter":
            raise RuntimeError("tk unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    service._show_startup_error_dialog("message")


def test_startup_show_error_dialog_displays_message_when_tk_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StartupService(project_root=Path("."))
    calls: dict[str, object] = {}

    class _Root:
        def withdraw(self) -> None:
            calls["withdraw"] = True

        def destroy(self) -> None:
            calls["destroy"] = True

    def _showerror(title: str, message: str) -> None:
        calls["title"] = title
        calls["message"] = message

    tk_module = types.ModuleType("tkinter")
    tk_module.Tk = _Root  # type: ignore[attr-defined]
    tk_module.messagebox = types.SimpleNamespace(showerror=_showerror)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tkinter", tk_module)

    service._show_startup_error_dialog("hello")
    assert calls["title"] == "Lexicon Startup Error"
    assert calls["message"] == "hello"
    assert calls["withdraw"] is True
    assert calls["destroy"] is True


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


