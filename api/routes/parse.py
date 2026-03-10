from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.dependencies import dep_parse_use_case, get_executor
from api.jobs import create_job, get_queue, cleanup_job, push_event
from api.schemas.parse_schemas import ParseJobResponse, ParseRequest, RowSyncRequest
from core.use_cases import ParseAndSyncInteractor

router = APIRouter()

_PARSE_COLUMNS = ["token", "normalized", "lemma", "categories", "source", "matched_form", "confidence", "known"]


def _serialize_parse_rows(table: list[list[object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for fallback_index, row in enumerate(table, start=1):
        values = list(row)
        if len(values) >= len(_PARSE_COLUMNS) + 1:
            raw_index = values[0]
            values = values[1:]
        else:
            raw_index = fallback_index

        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = fallback_index

        entry: dict[str, object] = {"index": index}
        for col, val in zip(_PARSE_COLUMNS, values):
            if col == "known":
                normalized = str(val).strip().lower()
                if normalized in {"yes", "true", "1"}:
                    entry[col] = "true"
                elif normalized in {"no", "false", "0"}:
                    entry[col] = "false"
                else:
                    entry[col] = str(val)
                continue
            entry[col] = "" if val is None else str(val)
        for col in _PARSE_COLUMNS:
            entry.setdefault(col, "")
        rows.append(entry)
    return rows


@router.post("/parse", response_model=ParseJobResponse)
async def start_parse(
    req: ParseRequest,
    parse_uc: ParseAndSyncInteractor = Depends(dep_parse_use_case),
):
    job_id = create_job()
    loop = asyncio.get_event_loop()
    executor = get_executor()

    def worker():
        push_event(loop, job_id, {"type": "progress", "message": "Parsing..."})
        try:
            result = parse_uc.execute(
                text=req.text,
                sync=req.sync,
                third_pass_enabled=req.third_pass_enabled,
                think_mode=req.think_mode,
            )
            if result.success and result.data is not None:
                rows = _serialize_parse_rows(result.data.table)
                push_event(loop, job_id, {
                    "type": "result",
                    "rows": rows,
                    "summary": result.data.summary,
                    "status_message": result.data.status_message,
                    "error_message": result.data.error_message,
                })
            else:
                push_event(loop, job_id, {
                    "type": "error",
                    "message": result.error_message or "Parse failed.",
                })
        except Exception as exc:
            push_event(loop, job_id, {"type": "error", "message": str(exc)})
        finally:
            push_event(loop, job_id, {"type": "done"})

    executor.submit(worker)
    return {"job_id": job_id}


@router.get("/parse/jobs/{job_id}/stream")
async def stream_parse_job(job_id: str):
    queue = get_queue(job_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    yield "data: {\"type\": \"error\", \"message\": \"Timeout\"}\n\n"
                    break
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
        finally:
            cleanup_job(job_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/parse/sync-row")
async def sync_row(
    req: RowSyncRequest,
    parse_uc: ParseAndSyncInteractor = Depends(dep_parse_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(),
        lambda: parse_uc.sync_single_row(
            token=req.token,
            normalized=req.normalized,
            lemma=req.lemma,
            categories=req.categories,
        ),
    )
    if result.success and result.data is not None:
        d = result.data
        return {
            "status": d.status,
            "value": d.value,
            "category": d.category,
            "request_id": d.request_id,
            "message": d.message,
            "category_fallback_used": d.category_fallback_used,
        }
    return {"status": "error", "message": result.error_message or "Sync failed."}
