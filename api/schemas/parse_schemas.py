from __future__ import annotations
from pydantic import BaseModel


class ParseRequest(BaseModel):
    text: str
    sync: bool = False
    third_pass_enabled: bool = False
    think_mode: bool = False


class ParseJobResponse(BaseModel):
    job_id: str


class RowSyncRequest(BaseModel):
    token: str
    normalized: str
    lemma: str
    categories: str
