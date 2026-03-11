"""Asynchronous AI warmup coordinator without UI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import threading
import time


@dataclass(frozen=True, slots=True)
class InitializationSnapshot:
    running: bool
    ready: bool
    failed: bool
    started_at: float | None
    finished_at: float | None
    error_message: str


class InitializationCoordinator:
    """Coordinate background warmup for semantic/AI services."""

    def __init__(
        self,
        *,
        project_root: Path,
        db_path: Path,
        logger: logging.Logger | None = None,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._db_path = Path(db_path).resolve()
        self._logger = logger or logging.getLogger("infrastructure.bootstrap.initialization_coordinator")

        self._lock = threading.Lock()
        self._started = False
        self._running = False
        self._ready = False
        self._failed = False
        self._error_message = ""
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        with self._lock:
            if self._started:
                return False
            self._started = True
            self._running = True
            self._started_at = time.perf_counter()
            worker = threading.Thread(
                target=self._warmup_worker,
                name="semantic_ai_warmup_thread",
                daemon=True,
            )
            self._thread = worker
            worker.start()
        return True

    def snapshot(self) -> InitializationSnapshot:
        with self._lock:
            return InitializationSnapshot(
                running=self._running,
                ready=self._ready,
                failed=self._failed,
                started_at=self._started_at,
                finished_at=self._finished_at,
                error_message=self._error_message,
            )

    def wait(self, timeout_seconds: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout_seconds)
        return not thread.is_alive()

    def _warmup_worker(self) -> None:
        try:
            self._warmup_semantic_engine()
            with self._lock:
                self._ready = True
                self._failed = False
                self._running = False
                self._finished_at = time.perf_counter()
                self._error_message = ""
            self._logger.info("ai_warmup_complete")
        except Exception as exc:  # pragma: no cover - runtime safety
            with self._lock:
                self._ready = False
                self._failed = True
                self._running = False
                self._finished_at = time.perf_counter()
                self._error_message = str(exc)
            self._logger.error("ai_warmup_failed error=%s", exc, exc_info=True)

    def _warmup_semantic_engine(self) -> None:
        from backend.python_services.infrastructure.config import PipelineSettings
        try:
            from skills.semantic_query_engine import SemanticQueryEngine
        except Exception as exc:
            self._logger.warning(
                "ai_warmup_semantic_engine_skipped_missing_skill error=%s",
                exc,
            )
            return

        try:
            import spacy
        except Exception as exc:
            self._logger.warning("ai_warmup_semantic_engine_skipped_spacy_import error=%s", exc)
            return

        settings = PipelineSettings.from_env()
        model_name = str(settings.spacy_trf_model_name).strip() or "en_core_web_trf"
        try:
            nlp = spacy.load(model_name)
        except Exception as exc:
            self._logger.warning(
                "ai_warmup_semantic_engine_skipped_model_load model=%s error=%s",
                model_name,
                exc,
            )
            return
        _ = nlp("Semantic warmup probe.")

        try:
            engine = SemanticQueryEngine(db_path=self._db_path)
            _ = engine.execute(query="show last 1 entries", context={"limit": 1})
        except Exception as exc:
            self._logger.warning(
                "ai_warmup_semantic_engine_skipped_engine_probe error=%s",
                exc,
            )
