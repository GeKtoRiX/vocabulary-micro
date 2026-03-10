from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import sys
import time
import traceback
from typing import Any, Protocol


@dataclass(frozen=True)
class StartupContext:
    project_root: Path
    db_path: Path
    logs_dir: Path
    app_log_path: Path
    startup_error_log_path: Path


@dataclass(frozen=True)
class PipelineStartupProbeResult:
    status: str
    reason: str
    duration_ms: float
    first_pass_status: str
    first_pass_error: str
    second_pass_status: str
    second_pass_reason: str
    detect_status: str
    detect_reason: str
    trf_model_available: bool | None
    trf_model_unavailable_reason: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class _PipelineProbeRepository(Protocol):
    def pipeline_status(self) -> dict[str, Any]:
        ...

    def parse_text(self, text: str, request_id: str | None = None) -> dict[str, Any]:
        ...

    def parse_mwe_text(
        self,
        text: str,
        *,
        request_id: str | None = None,
        top_n: int = 3,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        ...


class _PipelineProbeLogger(Protocol):
    def info(self, message: str) -> None:
        ...

    def warning(self, message: str) -> None:
        ...

    def error(self, message: str) -> None:
        ...


class StartupService:
    _PIPELINE_PROBE_FIRST_PASS_TEXT = "Startup probe text. This parser warmup should succeed."
    _PIPELINE_PROBE_SECOND_PASS_TEXT = "Please fill in the form before submission."
    _PIPELINE_PROBE_FIRST_PASS_REQUEST_ID = "startup_pipeline_probe_first_pass"
    _PIPELINE_PROBE_SECOND_PASS_REQUEST_ID = "startup_pipeline_probe_second_pass"
    _TRF_UNAVAILABLE_REASONS = {
        "spacy_unavailable",
        "spacy_model_unavailable",
        "spacy_model_load_failed",
    }

    def __init__(self, project_root: Path) -> None:
        self._project_root = Path(project_root).resolve()

    @property
    def project_root(self) -> Path:
        return self._project_root

    def initialize(self, *, db_path: Path | None = None) -> StartupContext:
        resolved_db_path = (
            Path(db_path).expanduser().resolve()
            if db_path is not None
            else self._default_db_path()
        )
        logs_dir = self._default_logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._apply_sql_migrations(db_path=resolved_db_path)
        app_log_path = logs_dir / "app.log"
        startup_error_log_path = logs_dir / "startup_error.log"
        return StartupContext(
            project_root=self._project_root,
            db_path=resolved_db_path,
            logs_dir=logs_dir,
            app_log_path=app_log_path,
            startup_error_log_path=startup_error_log_path,
        )

    def handle_startup_import_error(self, *, context: StartupContext, error: ImportError) -> None:
        details = (
            "Unable to start application because required modules were not imported.\n"
            "Activate .venv, install requirements, and ensure PYTHONPATH points to project root."
        )
        log_path = self._write_startup_error_log(
            context=context,
            title="STARTUP IMPORT ERROR",
            details=details,
            error=error,
        )
        message = f"{details}\n\nDetails: {error}\nLog: {log_path}"
        print(message, file=sys.stderr)
        self._show_startup_error_dialog(message)

    def handle_unexpected_startup_error(self, *, context: StartupContext, error: Exception) -> None:
        details = "Application failed during startup."
        log_path = self._write_startup_error_log(
            context=context,
            title="STARTUP ERROR",
            details=details,
            error=error,
        )
        message = f"{details}\n\nDetails: {error}\nLog: {log_path}"
        print(message, file=sys.stderr)
        self._show_startup_error_dialog(message)

    def probe_pipeline_on_startup(
        self,
        *,
        repository: _PipelineProbeRepository,
        logger: _PipelineProbeLogger,
    ) -> PipelineStartupProbeResult:
        started = time.perf_counter()
        try:
            pipeline_status = repository.pipeline_status()
            first_pass = repository.parse_text(
                self._PIPELINE_PROBE_FIRST_PASS_TEXT,
                request_id=self._PIPELINE_PROBE_FIRST_PASS_REQUEST_ID,
            )
            second_pass = repository.parse_mwe_text(
                self._PIPELINE_PROBE_SECOND_PASS_TEXT,
                request_id=self._PIPELINE_PROBE_SECOND_PASS_REQUEST_ID,
                top_n=1,
                enabled=True,
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
            report = PipelineStartupProbeResult(
                status="failed",
                reason="probe_exception",
                duration_ms=duration_ms,
                first_pass_status="failed",
                first_pass_error=str(exc),
                second_pass_status="failed",
                second_pass_reason="probe_exception",
                detect_status="failed",
                detect_reason="probe_exception",
                trf_model_available=None,
                trf_model_unavailable_reason="",
            )
            self._log_pipeline_probe_result(logger=logger, report=report)
            return report

        report = self._build_pipeline_probe_report(
            pipeline_status_payload=pipeline_status,
            first_pass_payload=first_pass,
            second_pass_payload=second_pass,
            duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )
        self._log_pipeline_probe_result(logger=logger, report=report)
        return report

    def _default_db_path(self) -> Path:
        return self._project_root / "infrastructure" / "persistence" / "data" / "lexicon.sqlite3"

    def _default_logs_dir(self) -> Path:
        return self._project_root / "infrastructure" / "runtime" / "logs"

    def _migrations_dir(self) -> Path:
        return self._project_root / "infrastructure" / "migrations"

    def _apply_sql_migrations(self, *, db_path: Path) -> None:
        migrations_dir = self._migrations_dir()
        if not migrations_dir.exists():
            return
        migration_files = sorted(migrations_dir.glob("*.sql"))
        if not migration_files:
            return

        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            self._ensure_migration_table(conn)

            lexicon_entries_exists = bool(
                conn.execute(
                    """
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'lexicon_entries'
                    LIMIT 1
                    """
                ).fetchone()
            )
            if not lexicon_entries_exists:
                return

            for migration_path in migration_files:
                migration_name = migration_path.name
                if self._migration_applied(conn, migration_name=migration_name):
                    continue
                sql = migration_path.read_text(encoding="utf-8")
                conn.executescript(sql)
                self._mark_migration_applied(conn, migration_name=migration_name)
            conn.commit()

    def _ensure_migration_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _migration_applied(self, conn: sqlite3.Connection, *, migration_name: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM schema_migrations
            WHERE name = ?
            LIMIT 1
            """,
            (migration_name,),
        ).fetchone()
        return bool(row)

    def _mark_migration_applied(self, conn: sqlite3.Connection, *, migration_name: str) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(name)
            VALUES (?)
            """,
            (migration_name,),
        )

    def _write_startup_error_log(
        self,
        *,
        context: StartupContext,
        title: str,
        details: str,
        error: Exception,
    ) -> Path:
        log_path = context.startup_error_log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{title}\n")
            handle.write(f"{details}\n")
            handle.write(f"{error.__class__.__name__}: {error}\n")
            handle.write(traceback.format_exc())
            handle.write("\n")
        return log_path

    def _show_startup_error_dialog(self, message: str) -> None:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Lexicon Startup Error", message)
            root.destroy()
        except Exception:
            # Best-effort fallback only; stderr log remains the primary channel.
            return

    def _build_pipeline_probe_report(
        self,
        *,
        pipeline_status_payload: dict[str, Any],
        first_pass_payload: dict[str, Any],
        second_pass_payload: dict[str, Any],
        duration_ms: float,
    ) -> PipelineStartupProbeResult:
        first_pass_status = str(first_pass_payload.get("pipeline_status", "unknown")).strip().lower()
        if not first_pass_status:
            first_pass_status = "unknown"
        first_pass_error = str(first_pass_payload.get("error", "")).strip()

        second_pass_status = str(second_pass_payload.get("status", "unknown")).strip().lower()
        if not second_pass_status:
            second_pass_status = "unknown"
        second_pass_reason = str(second_pass_payload.get("reason", "")).strip().lower()

        detect_status = "not_run"
        detect_reason = ""
        stage_statuses = second_pass_payload.get("stage_statuses")
        if isinstance(stage_statuses, list):
            for stage in stage_statuses:
                if not isinstance(stage, dict):
                    continue
                stage_name = str(stage.get("stage", "")).strip().lower()
                if stage_name != "mwe_detect":
                    continue
                detect_status = str(stage.get("status", "")).strip().lower() or "unknown"
                detect_reason = str(stage.get("reason", "")).strip().lower()
                break

        trf_model_available: bool | None = None
        trf_model_unavailable_reason = ""
        model_info = second_pass_payload.get("model_info")
        if isinstance(model_info, dict):
            availability = model_info.get("spacy_model_available")
            if isinstance(availability, bool):
                trf_model_available = availability
            trf_model_unavailable_reason = str(
                model_info.get("spacy_model_unavailable_reason", "")
            ).strip().lower()
        if trf_model_available is None and isinstance(pipeline_status_payload, dict):
            spacy_available = pipeline_status_payload.get("spacy_available")
            if isinstance(spacy_available, bool):
                trf_model_available = spacy_available

        status = "ok"
        reason = ""
        if first_pass_status == "failed" or bool(first_pass_error):
            status = "failed"
            reason = "first_pass_failed"
        elif second_pass_status == "failed":
            status = "failed"
            reason = second_pass_reason or "second_pass_failed"
        elif (
            second_pass_status == "skipped"
            or detect_status == "skipped"
            or trf_model_available is False
            or second_pass_reason in self._TRF_UNAVAILABLE_REASONS
            or detect_reason in self._TRF_UNAVAILABLE_REASONS
            or trf_model_unavailable_reason in self._TRF_UNAVAILABLE_REASONS
        ):
            status = "degraded"
            reason = (
                detect_reason
                or second_pass_reason
                or trf_model_unavailable_reason
                or "second_pass_degraded"
            )

        return PipelineStartupProbeResult(
            status=status,
            reason=reason,
            duration_ms=float(duration_ms),
            first_pass_status=first_pass_status,
            first_pass_error=first_pass_error,
            second_pass_status=second_pass_status,
            second_pass_reason=second_pass_reason,
            detect_status=detect_status,
            detect_reason=detect_reason,
            trf_model_available=trf_model_available,
            trf_model_unavailable_reason=trf_model_unavailable_reason,
        )

    def _log_pipeline_probe_result(
        self,
        *,
        logger: _PipelineProbeLogger,
        report: PipelineStartupProbeResult,
    ) -> None:
        payload = (
            "startup_pipeline_probe "
            f"status={report.status} "
            f"reason={report.reason or 'none'} "
            f"first_pass_status={report.first_pass_status} "
            f"second_pass_status={report.second_pass_status} "
            f"second_pass_reason={report.second_pass_reason or 'none'} "
            f"detect_status={report.detect_status} "
            f"detect_reason={report.detect_reason or 'none'} "
            f"trf_model_available={report.trf_model_available} "
            f"trf_model_unavailable_reason={report.trf_model_unavailable_reason or 'none'} "
            f"duration_ms={report.duration_ms:.3f}"
        )
        if report.first_pass_error:
            payload = f"{payload} first_pass_error={report.first_pass_error}"
        if report.status == "ok":
            logger.info(payload)
            return
        if report.status == "degraded":
            logger.warning(payload)
            return
        logger.error(payload)
