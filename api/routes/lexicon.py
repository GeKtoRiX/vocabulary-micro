from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.dependencies import dep_manage_use_case, dep_export_use_case, get_executor
from api.schemas.lexicon_schemas import (
    AddEntryRequest,
    BulkStatusRequest,
    CategoryRequest,
    DeleteEntriesRequest,
    LexiconSearchRequest,
    UpdateEntryRequest,
)
from core.domain.models import LexiconQuery
from core.use_cases import ManageLexiconInteractor, ExportLexiconInteractor

router = APIRouter()


def _query_from_req(req: LexiconSearchRequest) -> LexiconQuery:
    return LexiconQuery(
        status=req.status,
        limit=req.limit,
        offset=req.offset,
        value_filter=req.value_filter,
        category_filter=req.category_filter,
        source_filter=req.source_filter,
        request_filter=req.request_filter,
        sort_by=req.sort_by,
        sort_direction=req.sort_direction,
        semantic_raw_query=req.semantic_raw_query,
        id_min=req.id_min,
        id_max=req.id_max,
        reviewed_by_filter=req.reviewed_by_filter,
        confidence_min=req.confidence_min,
        confidence_max=req.confidence_max,
    )


def _serialize_search_result(result):
    return {
        "rows": [
            {
                "id": r.id,
                "category": r.category,
                "value": r.value,
                "normalized": r.normalized,
                "source": r.source,
                "confidence": r.confidence,
                "first_seen_at": r.first_seen_at,
                "request_id": r.request_id,
                "status": r.status,
                "created_at": r.created_at,
                "reviewed_at": r.reviewed_at,
                "reviewed_by": r.reviewed_by,
                "review_note": r.review_note,
            }
            for r in result.rows
        ],
        "total_rows": result.total_rows,
        "filtered_rows": result.filtered_rows,
        "counts_by_status": result.counts_by_status,
        "available_categories": result.available_categories,
        "message": result.message,
    }


@router.get("/lexicon/entries")
async def search_entries(
    status: str = "all",
    limit: int = 100,
    offset: int = 0,
    value_filter: str = "",
    category_filter: str = "",
    source_filter: str = "all",
    request_filter: str = "",
    sort_by: str = "id",
    sort_direction: str = "desc",
    semantic_raw_query: str | None = None,
    id_min: int | None = None,
    id_max: int | None = None,
    reviewed_by_filter: str = "",
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    manage_uc: ManageLexiconInteractor = Depends(dep_manage_use_case),
):
    query = LexiconQuery(
        status=status, limit=limit, offset=offset,
        value_filter=value_filter, category_filter=category_filter,
        source_filter=source_filter, request_filter=request_filter,
        sort_by=sort_by, sort_direction=sort_direction,
        semantic_raw_query=semantic_raw_query,
        id_min=id_min, id_max=id_max,
        reviewed_by_filter=reviewed_by_filter,
        confidence_min=confidence_min, confidence_max=confidence_max,
    )
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(get_executor(), lambda: manage_uc.search(query))
    if not result.success or result.data is None:
        raise HTTPException(status_code=500, detail=result.error_message)
    return _serialize_search_result(result.data)


@router.post("/lexicon/entries")
async def add_entry(
    req: AddEntryRequest,
    manage_uc: ManageLexiconInteractor = Depends(dep_manage_use_case),
):
    loop = asyncio.get_event_loop()
    repo = manage_uc._lexicon_repository  # type: ignore[attr-defined]
    await loop.run_in_executor(
        get_executor(),
        lambda: (
            repo.add_entry(
                category=req.category,
                value=req.value,
                source=req.source,
                confidence=req.confidence,
            ),
            repo.save(),
        ),
    )
    return {"message": f"Entry '{req.value}' added to '{req.category}'."}


@router.patch("/lexicon/entries/{entry_id}")
async def update_entry(
    entry_id: int,
    req: UpdateEntryRequest,
    manage_uc: ManageLexiconInteractor = Depends(dep_manage_use_case),
):
    query = _query_from_req(req.query)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(),
        lambda: manage_uc.update_entry(
            entry_id=entry_id,
            status=req.status,
            category=req.category,
            value=req.value,
            query=query,
        ),
    )
    if result.data is not None:
        return _serialize_search_result(result.data)
    raise HTTPException(status_code=500, detail=result.error_message)


@router.delete("/lexicon/entries")
async def delete_entries(
    req: DeleteEntriesRequest,
    manage_uc: ManageLexiconInteractor = Depends(dep_manage_use_case),
):
    query = _query_from_req(req.query)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(),
        lambda: manage_uc.delete_entries(entry_ids=req.entry_ids, query=query),
    )
    if result.data is not None:
        return _serialize_search_result(result.data)
    raise HTTPException(status_code=500, detail=result.error_message)


@router.post("/lexicon/entries/bulk-status")
async def bulk_update_status(
    req: BulkStatusRequest,
    manage_uc: ManageLexiconInteractor = Depends(dep_manage_use_case),
):
    query = _query_from_req(req.query)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(),
        lambda: manage_uc.bulk_update_status(
            entry_ids=req.entry_ids, status=req.status, query=query
        ),
    )
    if result.data is not None:
        return _serialize_search_result(result.data)
    raise HTTPException(status_code=500, detail=result.error_message)


@router.post("/lexicon/categories")
async def create_category(
    req: CategoryRequest,
    manage_uc: ManageLexiconInteractor = Depends(dep_manage_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(), lambda: manage_uc.create_category(req.name)
    )
    if result.success and result.data is not None:
        return {"categories": result.data.categories, "message": result.data.message}
    raise HTTPException(status_code=400, detail=result.error_message)


@router.delete("/lexicon/categories/{name}")
async def delete_category(
    name: str,
    manage_uc: ManageLexiconInteractor = Depends(dep_manage_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(), lambda: manage_uc.delete_category(name)
    )
    if result.success and result.data is not None:
        return {"categories": result.data.categories, "message": result.data.message}
    raise HTTPException(status_code=400, detail=result.error_message)


@router.get("/lexicon/export")
async def export_lexicon(
    export_uc: ExportLexiconInteractor = Depends(dep_export_use_case),
):
    tmp_path = Path(tempfile.mktemp(suffix=".xlsx"))
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        get_executor(), lambda: export_uc.execute(output_path=tmp_path)
    )
    if result.success and result.output_path and Path(result.output_path).exists():
        return FileResponse(
            path=str(result.output_path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="lexicon_export.xlsx",
        )
    raise HTTPException(status_code=500, detail=result.message)
