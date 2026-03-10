"""Job registry for SSE streams: job_id → asyncio.Queue."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any


_jobs: dict[str, asyncio.Queue[dict[str, Any]]] = {}


def create_job() -> str:
    job_id = uuid.uuid4().hex
    _jobs[job_id] = asyncio.Queue()
    return job_id


def get_queue(job_id: str) -> asyncio.Queue[dict[str, Any]] | None:
    return _jobs.get(job_id)


def cleanup_job(job_id: str) -> None:
    _jobs.pop(job_id, None)


def push_event(loop: asyncio.AbstractEventLoop, job_id: str, event: dict[str, Any]) -> None:
    """Push an event from a worker thread into the asyncio queue."""
    queue = _jobs.get(job_id)
    if queue is not None:
        loop.call_soon_threadsafe(queue.put_nowait, event)
