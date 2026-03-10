from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import Event, Lock, Thread, local as threading_local
import time
from typing import Callable

from core.domain import ILoggingService
from core.domain.services import AsyncSyncJob
from infrastructure.sqlite.text_utils import safe_ensure_column


class PersistentAsyncSyncQueue:
    def __init__(
        self,
        *,
        handler: Callable[[AsyncSyncJob], dict[str, object]],
        max_size: int,
        db_path: str | Path,
        worker_count: int = 1,
        poll_interval_ms: int = 150,
        max_attempts: int = 3,
        name: str = "clean_lexicon_persistent_async_sync",
        logger: ILoggingService | None = None,
    ) -> None:
        self._handler = handler
        self._max_size = max(1, int(max_size))
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._poll_interval = max(10, int(poll_interval_ms)) / 1000.0
        self._max_attempts = max(1, int(max_attempts))
        self._name = str(name)
        self._logger = logger
        self._stop_event = Event()
        self._workers: list[Thread] = []
        self._lock = Lock()
        self._thread_local = threading_local()
        self._thread_connections: list[sqlite3.Connection] = []
        self._conn_lock = Lock()

        self._ensure_schema()
        self._recover_orphaned_processing_jobs()

        for idx in range(max(1, int(worker_count))):
            worker = Thread(target=self._worker_loop, name=f"{self._name}_worker_{idx}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def enqueue(self, job: AsyncSyncJob) -> tuple[bool, int]:
        with self._lock:
            if self._stop_event.is_set():
                return False, self.depth
            current_depth = self.depth
            if current_depth >= self._max_size:
                return False, current_depth
            self._insert_job(job)
            return True, self.depth

    @property
    def depth(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM async_sync_jobs
                WHERE status IN ('queued', 'processing')
                """
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def wait_for_idle(self, timeout_seconds: float = 2.0) -> bool:
        deadline = time.time() + max(0.0, float(timeout_seconds))
        while time.time() < deadline:
            if self.depth == 0:
                return True
            time.sleep(0.05)
        return self.depth == 0

    def shutdown(self, *, drain: bool = True, timeout_seconds: float = 2.0) -> dict[str, object]:
        self._stop_event.set()
        canceled_jobs = 0
        if drain:
            self.wait_for_idle(timeout_seconds=max(0.1, float(timeout_seconds)))
        else:
            canceled_jobs = self._clear_queued_jobs()

        for worker in self._workers:
            worker.join(timeout=max(0.1, float(timeout_seconds)))

        alive = sum(1 for worker in self._workers if worker.is_alive())
        report = {
            "drain": drain,
            "remaining_depth": self.depth,
            "canceled_jobs": canceled_jobs,
            "alive_workers": alive,
            "queue_db_path": str(self._db_path),
        }
        if alive > 0:
            self._log_error("persistent_async_sync_queue_shutdown_incomplete", RuntimeError(str(report)))
        else:
            self._log_info(f"persistent_async_sync_queue_shutdown_complete report={report}")
        self._close_all_connections()
        return report

    def _worker_loop(self) -> None:
        while True:
            if self._stop_event.is_set() and self.depth == 0:
                break
            claimed = self._claim_next_job()
            if claimed is None:
                time.sleep(self._poll_interval)
                continue

            job_id, job, attempts = claimed
            try:
                payload = self._handler(job)
                self._mark_done(job_id, payload=payload)
            except Exception as exc:
                self._mark_failed(job_id, attempts=attempts, error=str(exc))
                self._log_error("persistent_async_sync_queue_handler", exc)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS async_sync_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    auto_add_category TEXT NOT NULL,
                    candidates_json TEXT NOT NULL,
                    candidate_categories_json TEXT,
                    enqueued_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_error TEXT,
                    result_json TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_async_sync_jobs_status_id
                ON async_sync_jobs(status, id);
                """
            )
            self._ensure_column(
                conn,
                table_name="async_sync_jobs",
                column_name="candidate_categories_json",
                column_def="TEXT",
            )

    def _recover_orphaned_processing_jobs(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE async_sync_jobs
                SET status = 'queued',
                    updated_at = ?
                WHERE status = 'processing'
                """,
                (self._now_iso(),),
            )

    def _insert_job(self, job: AsyncSyncJob) -> None:
        candidates_json = json.dumps(list(job.candidates), ensure_ascii=True)
        candidate_categories_json = json.dumps(list(job.candidate_categories), ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO async_sync_jobs(
                    request_id,
                    auto_add_category,
                    candidates_json,
                    candidate_categories_json,
                    enqueued_at,
                    status,
                    attempts,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'queued', 0, ?)
                """,
                (
                    job.request_id,
                    job.auto_add_category,
                    candidates_json,
                    candidate_categories_json,
                    float(job.enqueued_at_epoch),
                    self._now_iso(),
                ),
            )

    def _claim_next_job(self) -> tuple[int, AsyncSyncJob, int] | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                """
                SELECT
                    id,
                    request_id,
                    auto_add_category,
                    candidates_json,
                    candidate_categories_json,
                    enqueued_at,
                    attempts
                FROM async_sync_jobs
                WHERE status = 'queued' AND attempts < ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (self._max_attempts,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT;")
                return None
            conn.execute(
                """
                UPDATE async_sync_jobs
                SET status = 'processing',
                    updated_at = ?
                WHERE id = ?
                """,
                (self._now_iso(), int(row["id"])),
            )
            conn.execute("COMMIT;")

        candidates = tuple(json.loads(str(row["candidates_json"])))
        raw_categories = row["candidate_categories_json"]
        candidate_categories: tuple[tuple[str, str], ...] = tuple()
        if raw_categories:
            try:
                parsed_categories = json.loads(str(raw_categories))
                candidate_categories = tuple(
                    (
                        str(item[0]),
                        str(item[1]),
                    )
                    for item in parsed_categories
                    if isinstance(item, (list, tuple)) and len(item) >= 2
                )
            except Exception:
                candidate_categories = tuple()
        if not candidate_categories:
            candidate_categories = tuple((candidate, str(row["auto_add_category"])) for candidate in candidates)

        job = AsyncSyncJob(
            request_id=str(row["request_id"]),
            candidates=candidates,
            auto_add_category=str(row["auto_add_category"]),
            candidate_categories=candidate_categories,
            enqueued_at_epoch=float(row["enqueued_at"]),
        )
        return int(row["id"]), job, int(row["attempts"])

    def _mark_done(self, job_id: int, *, payload: dict[str, object]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE async_sync_jobs
                SET status = 'done',
                    result_json = ?,
                    updated_at = ?,
                    last_error = NULL
                WHERE id = ?
                """,
                (json.dumps(payload, ensure_ascii=True), self._now_iso(), int(job_id)),
            )

    def _mark_failed(self, job_id: int, *, attempts: int, error: str) -> None:
        next_attempts = int(attempts) + 1
        next_status = "failed" if next_attempts >= self._max_attempts else "queued"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE async_sync_jobs
                SET status = ?,
                    attempts = ?,
                    updated_at = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (next_status, next_attempts, self._now_iso(), str(error)[:2048], int(job_id)),
            )

    def _clear_queued_jobs(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM async_sync_jobs
                WHERE status = 'queued'
                """
            ).fetchone()
            count = int(row["count"]) if row is not None else 0
            conn.execute(
                """
                UPDATE async_sync_jobs
                SET status = 'canceled',
                    updated_at = ?
                WHERE status = 'queued'
                """,
                (self._now_iso(),),
            )
        return count

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._thread_local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        self._thread_local.conn = conn
        with self._conn_lock:
            self._thread_connections.append(conn)
        return conn

    def _close_all_connections(self) -> None:
        with self._conn_lock:
            for conn in self._thread_connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._thread_connections.clear()

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        *,
        table_name: str,
        column_name: str,
        column_def: str,
    ) -> None:
        safe_ensure_column(
            conn,
            table_name=table_name,
            column_name=column_name,
            column_def=column_def,
        )

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _log_info(self, message: str) -> None:
        if self._logger is None:
            return
        self._logger.info(message)

    def _log_error(self, operation: str, error: Exception) -> None:
        if self._logger is None:
            return
        self._logger.error(f"operation={operation} error={error}")
