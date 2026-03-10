from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from api.dependencies import dep_assignments_use_case, get_executor
from api.jobs import create_job, get_queue, cleanup_job, push_event
from api.schemas.assignment_schemas import (
    BulkIdsRequest,
    QuickAddRequest,
    ScanRequest,
    SuggestCategoryRequest,
    UpdateAssignmentRequest,
)
from core.use_cases import ManageAssignmentsInteractor

router = APIRouter()


def _serialize_scan_result(data):
    return {
        "assignment_id": data.assignment_id,
        "title": data.title,
        "content_original": data.content_original,
        "content_completed": data.content_completed,
        "word_count": data.word_count,
        "known_token_count": data.known_token_count,
        "unknown_token_count": data.unknown_token_count,
        "lexicon_coverage_percent": data.lexicon_coverage_percent,
        "assignment_status": data.assignment_status,
        "message": data.message,
        "duration_ms": data.duration_ms,
        "matches": [
            {
                "entry_id": m.entry_id,
                "term": m.term,
                "category": m.category,
                "source": m.source,
                "occurrences": m.occurrences,
            }
            for m in data.matches
        ],
        "missing_words": [
            {
                "term": w.term,
                "occurrences": w.occurrences,
                "example_usage": w.example_usage,
            }
            for w in data.missing_words
        ],
        "diff_chunks": [
            {
                "operation": c.operation,
                "original_text": c.original_text,
                "completed_text": c.completed_text,
            }
            for c in data.diff_chunks
        ],
    }


def _serialize_assignment(a):
    return {
        "id": a.id,
        "title": a.title,
        "content_original": a.content_original,
        "content_completed": a.content_completed,
        "status": a.status,
        "lexicon_coverage_percent": a.lexicon_coverage_percent,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


def _run_scan_job(
    job_id: str,
    loop: asyncio.AbstractEventLoop,
    assignments_uc: ManageAssignmentsInteractor,
    title: str,
    content_original: str,
    content_completed: str,
) -> None:
    push_event(loop, job_id, {"type": "progress", "message": "Scanning assignment..."})
    try:
        result = assignments_uc.scan_and_save(
            title=title or "Untitled Assignment",
            content_original=content_original,
            content_completed=content_completed,
        )
        if result.success and result.data is not None:
            push_event(loop, job_id, {"type": "result", "data": _serialize_scan_result(result.data)})
        else:
            push_event(loop, job_id, {"type": "error", "message": result.error_message or "Scan failed."})
    except Exception as exc:
        push_event(loop, job_id, {"type": "error", "message": str(exc)})
    finally:
        push_event(loop, job_id, {"type": "done"})


async def _sse_stream(job_id: str):
    queue = get_queue(job_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    yield 'data: {"type": "error", "message": "Timeout"}\n\n'
                    break
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
        finally:
            cleanup_job(job_id)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/assignments/scan")
async def scan_assignment(
    req: ScanRequest,
    assignments_uc: ManageAssignmentsInteractor = Depends(dep_assignments_use_case),
):
    job_id = create_job()
    loop = asyncio.get_event_loop()
    get_executor().submit(
        _run_scan_job,
        job_id, loop, assignments_uc,
        req.title, req.content_original, req.content_completed,
    )
    return {"job_id": job_id}


@router.get("/assignments/scan/jobs/{job_id}/stream")
async def stream_scan_job(job_id: str):
    return await _sse_stream(job_id)


@router.get("/assignments")
async def list_assignments(
    limit: int = 50,
    offset: int = 0,
    assignments_uc: ManageAssignmentsInteractor = Depends(dep_assignments_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(), lambda: assignments_uc.list_assignments(limit=limit, offset=offset)
    )
    if result.success and result.data is not None:
        return [_serialize_assignment(a) for a in result.data]
    raise HTTPException(status_code=500, detail=result.error_message)


@router.get("/assignments/{assignment_id}")
async def get_assignment(
    assignment_id: int,
    assignments_uc: ManageAssignmentsInteractor = Depends(dep_assignments_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(), lambda: assignments_uc.get_assignment(assignment_id=assignment_id)
    )
    if result.success and result.data is not None:
        return _serialize_assignment(result.data)
    raise HTTPException(status_code=404, detail=result.error_message)


@router.put("/assignments/{assignment_id}")
async def update_assignment(
    assignment_id: int,
    req: UpdateAssignmentRequest,
    assignments_uc: ManageAssignmentsInteractor = Depends(dep_assignments_use_case),
):
    job_id = create_job()
    loop = asyncio.get_event_loop()

    def worker():
        push_event(loop, job_id, {"type": "progress", "message": "Updating assignment..."})
        try:
            result = assignments_uc.update_assignment(
                assignment_id=assignment_id,
                title=req.title or "Untitled Assignment",
                content_original=req.content_original,
                content_completed=req.content_completed,
            )
            if result.success and result.data is not None:
                push_event(loop, job_id, {"type": "result", "data": _serialize_scan_result(result.data)})
            else:
                push_event(loop, job_id, {"type": "error", "message": result.error_message or "Update failed."})
        except Exception as exc:
            push_event(loop, job_id, {"type": "error", "message": str(exc)})
        finally:
            push_event(loop, job_id, {"type": "done"})

    get_executor().submit(worker)
    return {"job_id": job_id}


@router.delete("/assignments/{assignment_id}")
async def delete_assignment(
    assignment_id: int,
    assignments_uc: ManageAssignmentsInteractor = Depends(dep_assignments_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(), lambda: assignments_uc.delete_assignment(assignment_id=assignment_id)
    )
    if result.success:
        return {"deleted": True, "message": "Assignment deleted."}
    return {"deleted": False, "message": result.error_message or "Delete failed."}


@router.post("/assignments/bulk-delete")
async def bulk_delete(
    req: BulkIdsRequest,
    assignments_uc: ManageAssignmentsInteractor = Depends(dep_assignments_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(),
        lambda: assignments_uc.bulk_delete_assignments(assignment_ids=req.assignment_ids),
    )
    data = result.data
    if data is not None:
        return {
            "operation": data.operation,
            "success_count": data.success_count,
            "failed_count": data.failed_count,
            "message": data.message,
        }
    raise HTTPException(status_code=500, detail=result.error_message)


@router.post("/assignments/bulk-rescan")
async def bulk_rescan(
    req: BulkIdsRequest,
    assignments_uc: ManageAssignmentsInteractor = Depends(dep_assignments_use_case),
):
    job_id = create_job()
    loop = asyncio.get_event_loop()

    def worker():
        push_event(loop, job_id, {"type": "progress", "message": "Rescanning assignments..."})
        try:
            result = assignments_uc.bulk_rescan_assignments(assignment_ids=req.assignment_ids)
            data = result.data
            if data is not None:
                push_event(loop, job_id, {
                    "type": "result",
                    "success_count": data.success_count,
                    "failed_count": data.failed_count,
                    "message": data.message,
                })
            else:
                push_event(loop, job_id, {"type": "error", "message": result.error_message or "Rescan failed."})
        except Exception as exc:
            push_event(loop, job_id, {"type": "error", "message": str(exc)})
        finally:
            push_event(loop, job_id, {"type": "done"})

    get_executor().submit(worker)
    return {"job_id": job_id}


@router.get("/assignments/{assignment_id}/audio")
async def get_audio(assignment_id: int):
    # Audio path stored in DB; look it up via the use case when speech is implemented
    raise HTTPException(status_code=404, detail="Audio not available")


@router.post("/assignments/quick-add")
async def quick_add(
    req: QuickAddRequest,
    assignments_uc: ManageAssignmentsInteractor = Depends(dep_assignments_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(),
        lambda: assignments_uc.quick_add_missing_word(
            assignment_id=req.assignment_id,
            term=req.term,
            content_completed=req.content_completed,
            category=req.category,
        ),
    )
    data = result.data
    if data is not None:
        return {
            "status": data.status,
            "value": data.value,
            "category": data.category,
            "request_id": data.request_id,
            "message": data.message,
            "category_fallback_used": data.category_fallback_used,
        }
    return {"status": "error", "message": result.error_message or "Quick add failed."}


@router.post("/assignments/suggest-category")
async def suggest_category(
    req: SuggestCategoryRequest,
    assignments_uc: ManageAssignmentsInteractor = Depends(dep_assignments_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(),
        lambda: assignments_uc.suggest_quick_add(
            term=req.term,
            content_completed=req.content_completed,
            available_categories=req.available_categories or None,
        ),
    )
    data = result.data
    if data is not None:
        return {
            "term": data.term,
            "recommended_category": data.recommended_category,
            "candidate_categories": list(data.candidate_categories),
            "confidence": data.confidence,
            "rationale": data.rationale,
            "suggested_example_usage": data.suggested_example_usage,
        }
    return {"term": req.term, "recommended_category": "", "candidate_categories": [], "confidence": 0.0, "rationale": "", "suggested_example_usage": ""}
