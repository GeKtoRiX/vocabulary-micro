from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class LexiconSearchRequest(BaseModel):
    status: str = "all"
    limit: int = 100
    offset: int = 0
    value_filter: str = ""
    category_filter: str = ""
    source_filter: str = "all"
    request_filter: str = ""
    sort_by: str = "id"
    sort_direction: str = "desc"
    semantic_raw_query: str | None = None
    id_min: int | None = None
    id_max: int | None = None
    reviewed_by_filter: str = ""
    confidence_min: float | None = None
    confidence_max: float | None = None


class UpdateEntryRequest(BaseModel):
    entry_id: int
    status: str
    category: str
    value: str
    query: LexiconSearchRequest = LexiconSearchRequest()


class DeleteEntriesRequest(BaseModel):
    entry_ids: list[int]
    query: LexiconSearchRequest = LexiconSearchRequest()


class BulkStatusRequest(BaseModel):
    entry_ids: list[int]
    status: str
    query: LexiconSearchRequest = LexiconSearchRequest()


class AddEntryRequest(BaseModel):
    category: str
    value: str
    source: str = "manual"
    confidence: float = 1.0


class CategoryRequest(BaseModel):
    name: str
