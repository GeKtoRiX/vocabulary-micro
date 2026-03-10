from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from api.dependencies import dep_coordinator

if TYPE_CHECKING:
    from infrastructure.bootstrap.initialization_coordinator import InitializationCoordinator

router = APIRouter()


@router.get("/system/health")
def health():
    return {"status": "ok"}


@router.get("/system/warmup")
def warmup_status(coordinator: "InitializationCoordinator" = Depends(dep_coordinator)):
    snap = coordinator.snapshot()
    elapsed: float | None = None
    if snap.started_at is not None and snap.finished_at is not None:
        elapsed = round(snap.finished_at - snap.started_at, 2)
    elif snap.started_at is not None:
        import time
        elapsed = round(time.perf_counter() - snap.started_at, 2)
    return {
        "running": snap.running,
        "ready": snap.ready,
        "failed": snap.failed,
        "error_message": snap.error_message,
        "elapsed_sec": elapsed,
    }
