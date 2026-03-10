from __future__ import annotations
from pydantic import BaseModel


class ScanRequest(BaseModel):
    title: str = ""
    content_original: str = ""
    content_completed: str


class UpdateAssignmentRequest(BaseModel):
    title: str = ""
    content_original: str = ""
    content_completed: str


class BulkIdsRequest(BaseModel):
    assignment_ids: list[int]


class QuickAddRequest(BaseModel):
    term: str
    content_completed: str
    category: str = ""
    assignment_id: int | None = None


class SuggestCategoryRequest(BaseModel):
    term: str
    content_completed: str
    available_categories: list[str] = []
