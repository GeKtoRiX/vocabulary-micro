from __future__ import annotations

from pathlib import Path

from core.domain.services import AsyncSyncJob
from infrastructure.adapters.sync_queue_adapter import PersistentAsyncSyncQueue


def test_persistent_async_sync_queue_processes_enqueued_job(tmp_path: Path) -> None:
    handled: list[str] = []

    def _handler(job: AsyncSyncJob) -> dict[str, object]:
        handled.extend(list(job.candidates))
        return {"status": "ok", "count": len(job.candidates)}

    queue = PersistentAsyncSyncQueue(
        handler=_handler,
        max_size=8,
        db_path=tmp_path / "sync_queue.sqlite3",
        worker_count=1,
        poll_interval_ms=20,
        max_attempts=2,
    )
    accepted, _ = queue.enqueue(
        AsyncSyncJob(
            request_id="req-1",
            candidates=("run", "fast"),
            auto_add_category="Auto Added",
            candidate_categories=(("run", "Verb"), ("fast", "Adverb")),
        )
    )
    assert accepted is True
    assert queue.wait_for_idle(timeout_seconds=2.0) is True
    report = queue.shutdown(drain=True, timeout_seconds=2.0)
    assert report["remaining_depth"] == 0
    assert handled == ["run", "fast"]


def test_persistent_async_sync_queue_retries_and_marks_done(tmp_path: Path) -> None:
    attempts = {"count": 0}

    def _handler(job: AsyncSyncJob) -> dict[str, object]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary failure")
        return {"status": "ok", "request_id": job.request_id}

    queue = PersistentAsyncSyncQueue(
        handler=_handler,
        max_size=8,
        db_path=tmp_path / "sync_queue.sqlite3",
        worker_count=1,
        poll_interval_ms=20,
        max_attempts=2,
    )
    accepted, _ = queue.enqueue(
        AsyncSyncJob(
            request_id="req-2",
            candidates=("retry",),
            auto_add_category="Auto Added",
            candidate_categories=(("retry", "Verb"),),
        )
    )
    assert accepted is True
    assert queue.wait_for_idle(timeout_seconds=2.0) is True
    report = queue.shutdown(drain=True, timeout_seconds=2.0)
    assert report["remaining_depth"] == 0
    assert attempts["count"] >= 2
