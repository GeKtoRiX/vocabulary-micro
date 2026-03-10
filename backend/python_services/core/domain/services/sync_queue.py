from __future__ import annotations

from dataclasses import dataclass, field
import queue
from threading import Event, Lock, Thread
import time
from typing import Callable, Protocol
import traceback

from ..logging_service import ILoggingService


@dataclass(frozen=True)
class AsyncSyncJob:
    request_id: str
    candidates: tuple[str, ...]
    auto_add_category: str
    candidate_categories: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    enqueued_at_epoch: float = field(default_factory=time.time)


class ISyncQueue(Protocol):
    def enqueue(self, job: AsyncSyncJob) -> tuple[bool, int]:
        ...

    @property
    def depth(self) -> int:
        ...

    def wait_for_idle(self, timeout_seconds: float = 2.0) -> bool:
        ...

    def shutdown(self, *, drain: bool = True, timeout_seconds: float = 2.0) -> dict[str, object]:
        ...


class AsyncSyncQueue:
    def __init__(
        self,
        *,
        handler: Callable[[AsyncSyncJob], dict[str, object]],
        max_size: int,
        worker_count: int = 1,
        name: str = "clean_lexicon_async_sync",
        logger: ILoggingService | None = None,
    ) -> None:
        self._handler = handler
        self._queue: queue.Queue[AsyncSyncJob] = queue.Queue(maxsize=max(1, int(max_size)))
        self._stop_event = Event()
        self._workers: list[Thread] = []
        self._lock = Lock()
        self._queued_jobs = 0
        self._in_flight_jobs = 0
        self._name = str(name)
        self._logger = logger

        for idx in range(max(1, int(worker_count))):
            worker = Thread(target=self._worker_loop, name=f"{self._name}_worker_{idx}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def enqueue(self, job: AsyncSyncJob) -> tuple[bool, int]:
        with self._lock:
            if self._stop_event.is_set():
                return False, int(self._queued_jobs)
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                return False, int(self._queued_jobs)
            self._queued_jobs += 1
            return True, int(self._queued_jobs)

    @property
    def depth(self) -> int:
        with self._lock:
            return int(self._queued_jobs)

    def stop(self, timeout_seconds: float = 1.0) -> None:
        self.shutdown(drain=True, timeout_seconds=timeout_seconds)

    def shutdown(self, *, drain: bool = True, timeout_seconds: float = 2.0) -> dict[str, object]:
        self._stop_event.set()
        timeout = max(0.1, float(timeout_seconds))
        canceled_jobs = 0
        waited_for_idle = False
        if not drain:
            canceled_jobs = self._clear_queued_jobs()
        else:
            waited_for_idle = self.wait_for_idle(timeout_seconds=timeout)

        join_deadline = time.monotonic() + timeout
        for worker in self._workers:
            remaining = max(0.0, join_deadline - time.monotonic())
            worker.join(timeout=remaining)

        alive = sum(1 for worker in self._workers if worker.is_alive())
        queued_jobs, in_flight_jobs, is_idle = self._snapshot_state()
        report = {
            "drain": drain,
            "waited_for_idle": waited_for_idle,
            "idle_reached": is_idle,
            "remaining_depth": queued_jobs,
            "in_flight_jobs": in_flight_jobs,
            "canceled_jobs": canceled_jobs,
            "alive_workers": alive,
        }
        if alive > 0:
            self._log_error("async_sync_queue_shutdown_incomplete", RuntimeError(str(report)))
        else:
            self._log_info(f"async_sync_queue_shutdown_complete report={report}")
        return report

    def wait_for_idle(self, timeout_seconds: float = 2.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            _, _, is_idle = self._snapshot_state()
            if is_idle:
                return True
            time.sleep(0.02)
        _, _, is_idle = self._snapshot_state()
        return is_idle

    def _worker_loop(self) -> None:
        while True:
            _, _, is_idle = self._snapshot_state()
            if self._stop_event.is_set() and is_idle:
                break
            job = self._claim_next_job()
            if job is None:
                time.sleep(0.02)
                continue
            try:
                self._handler(job)
            except Exception as exc:
                self._log_error("async_sync_queue_handler", exc)
            finally:
                self._queue.task_done()
                self._release_in_flight()

    def _snapshot_state(self) -> tuple[int, int, bool]:
        with self._lock:
            queued_jobs = int(self._queued_jobs)
            in_flight_jobs = int(self._in_flight_jobs)
            queue_empty = bool(self._queue.empty())
        is_idle = queue_empty and queued_jobs == 0 and in_flight_jobs == 0
        return queued_jobs, in_flight_jobs, is_idle

    def _claim_next_job(self) -> AsyncSyncJob | None:
        with self._lock:
            if self._queued_jobs <= 0:
                return None
            # Mark in-flight before pulling from queue to prevent idle races.
            self._in_flight_jobs += 1
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                self._in_flight_jobs = max(0, self._in_flight_jobs - 1)
                self._queued_jobs = 0
                return None
            self._queued_jobs = max(0, self._queued_jobs - 1)
            return job

    def _release_in_flight(self) -> None:
        with self._lock:
            self._in_flight_jobs = max(0, self._in_flight_jobs - 1)

    def _clear_queued_jobs(self) -> int:
        canceled_jobs = 0
        while True:
            with self._lock:
                if self._queued_jobs <= 0:
                    return canceled_jobs
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    self._queued_jobs = 0
                    return canceled_jobs
                self._queued_jobs = max(0, self._queued_jobs - 1)
            self._queue.task_done()
            canceled_jobs += 1

    def _log_info(self, message: str) -> None:
        if self._logger is None:
            return
        self._logger.info(message)

    def _log_error(self, operation: str, error: Exception) -> None:
        if self._logger is None:
            return
        self._logger.error(
            f"operation={operation} error={error} traceback={traceback.format_exc()}"
        )
