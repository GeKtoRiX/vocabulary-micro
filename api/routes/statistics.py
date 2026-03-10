from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import dep_statistics_use_case, get_executor
from core.use_cases import StatisticsInteractor

router = APIRouter()


@router.get("/statistics")
async def get_statistics(
    stats_uc: StatisticsInteractor = Depends(dep_statistics_use_case),
):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(get_executor(), stats_uc.execute)
    if result.success and result.data is not None:
        d = result.data
        top_category_name = d.categories[0][0] if d.categories else ""
        top_category_count = d.categories[0][1] if d.categories else 0
        return {
            "total_entries": d.total_entries,
            "counts_by_status": d.counts_by_status,
            "counts_by_source": d.counts_by_source,
            "categories": [{"name": name, "count": count} for name, count in d.categories],
            "assignment_coverage": [
                {"title": title, "coverage_pct": pct, "created_at": created_at}
                for title, pct, created_at in d.assignment_coverage
            ],
            "overview": {
                "total_assignments": d.total_assignments,
                "average_assignment_coverage": round(d.average_assignment_coverage, 1),
                "pending_review_count": int(d.counts_by_status.get("pending_review", 0)),
                "approved_count": int(d.counts_by_status.get("approved", 0)),
                "low_coverage_count": d.low_coverage_count,
                "top_category": {
                    "name": top_category_name,
                    "count": top_category_count,
                },
            },
        }
    raise HTTPException(status_code=500, detail=result.error_message)
