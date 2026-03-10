from __future__ import annotations

from threading import Event
import time

from core.domain.services import AsyncSyncJob, AsyncSyncQueue


def test_wait_for_idle_requires_no_in_flight_jobs() -> None:
    started = Event()
    release = Event()
    finished = Event()

    def _handler(job: AsyncSyncJob) -> dict[str, object]:
        started.set()
        release.wait(timeout=1.0)
        finished.set()
        return {"request_id": job.request_id}

    queue = AsyncSyncQueue(
        handler=_handler,
        max_size=4,
        worker_count=1,
        name="test_shutdown_race_wait_for_idle",
    )
    accepted, _ = queue.enqueue(
        AsyncSyncJob(
            request_id="req-wait",
            candidates=("run",),
            auto_add_category="Auto Added",
            candidate_categories=(("run", "Verb"),),
        )
    )
    assert accepted is True
    assert started.wait(timeout=1.0) is True

    # Must stay busy while handler is still running.
    assert queue.wait_for_idle(timeout_seconds=0.05) is False

    release.set()
    assert queue.wait_for_idle(timeout_seconds=1.0) is True
    report = queue.shutdown(drain=True, timeout_seconds=1.0)
    assert finished.is_set() is True
    assert report["remaining_depth"] == 0
    assert report["in_flight_jobs"] == 0
    assert report["alive_workers"] == 0


def test_shutdown_waits_for_slow_job_completion() -> None:
    started = Event()
    finished = Event()

    def _handler(job: AsyncSyncJob) -> dict[str, object]:
        started.set()
        time.sleep(0.25)
        finished.set()
        return {"request_id": job.request_id}

    queue = AsyncSyncQueue(
        handler=_handler,
        max_size=4,
        worker_count=1,
        name="test_shutdown_race_slow_job",
    )
    accepted, _ = queue.enqueue(
        AsyncSyncJob(
            request_id="req-slow",
            candidates=("slow",),
            auto_add_category="Auto Added",
            candidate_categories=(("slow", "Adjective"),),
        )
    )
    assert accepted is True
    assert started.wait(timeout=1.0) is True

    started_at = time.monotonic()
    report = queue.shutdown(drain=True, timeout_seconds=2.0)
    elapsed = time.monotonic() - started_at

    assert finished.is_set() is True
    assert elapsed >= 0.20
    assert report["idle_reached"] is True
    assert report["remaining_depth"] == 0
    assert report["in_flight_jobs"] == 0
    assert report["alive_workers"] == 0
