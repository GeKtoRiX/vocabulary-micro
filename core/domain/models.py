from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar


T = TypeVar("T")


EDITABLE_ENTRY_STATUSES = {"pending_review", "approved", "rejected"}


@dataclass
class TokenRecord:
    token: str
    normalized: str
    lemma: str
    pos: str
    start: int
    end: int
    categories: list[str] = field(default_factory=list)
    known: bool = False
    match_source: str = "none"
    matched_form: str = ""
    bert_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "normalized": self.normalized,
            "lemma": self.lemma,
            "pos": self.pos,
            "start": self.start,
            "end": self.end,
            "categories": list(self.categories),
            "known": self.known,
            "match_source": self.match_source,
            "matched_form": self.matched_form,
            "bert_score": self.bert_score,
        }


@dataclass(frozen=True)
class PhraseMatchRecord:
    phrase: str
    normalized: str
    start_token_index: int
    end_token_index: int
    categories: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phrase": self.phrase,
            "normalized": self.normalized,
            "start_token_index": self.start_token_index,
            "end_token_index": self.end_token_index,
            "categories": list(self.categories),
        }


@dataclass(frozen=True)
class PipelineStats:
    tokens_total: int
    known_tokens: int
    unknown_tokens: int
    coverage_percent: float
    source_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_total": self.tokens_total,
            "known_tokens": self.known_tokens,
            "unknown_tokens": self.unknown_tokens,
            "coverage_percent": self.coverage_percent,
            "source_counts": dict(self.source_counts),
        }


@dataclass(frozen=True)
class StageStatus:
    stage: str
    status: str
    duration_ms: float
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 3),
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ParseRequest:
    text: str
    sync: bool = False
    request_id: str | None = None
    third_pass_think_mode: bool | None = None
    third_pass_enabled: bool | None = None
    third_pass_timeout_ms: int | None = None

    @property
    def has_content(self) -> bool:
        return bool(str(self.text).strip())


@dataclass(frozen=True)
class ParseResult:
    table: list[list[str]]
    summary: dict[str, Any]


@dataclass(frozen=True)
class ParseAndSyncResultDTO:
    table: list[list[str]]
    summary: dict[str, Any]
    status_message: str
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return not bool(self.error_message)


@dataclass(frozen=True)
class ParseRowSyncResultDTO:
    status: str
    value: str
    category: str
    request_id: str
    message: str
    category_fallback_used: bool


@dataclass(frozen=True)
class CategoryMutationResult:
    categories: list[str]
    message: str


@dataclass(frozen=True, slots=True)
class LexiconEntryRecord:
    id: int
    category: str
    value: str
    normalized: str
    source: str
    confidence: float | None
    first_seen_at: str | None
    request_id: str | None
    status: str
    created_at: str | None
    reviewed_at: str | None
    reviewed_by: str | None
    review_note: str | None

    def to_table_row(self) -> list[object]:
        return [
            self.id,
            self.category,
            self.value,
            self.normalized,
            self.source,
            self.confidence,
            self.first_seen_at,
            self.request_id,
            self.status,
            self.created_at,
            self.reviewed_at,
            self.reviewed_by,
            self.review_note,
        ]


@dataclass(frozen=True, slots=True)
class LexiconQuery:
    status: str = "all"
    limit: int = 100
    offset: int = 0
    semantic_raw_query: str | None = None
    category_filter: str = ""
    value_filter: str = ""
    source_filter: str = "all"
    request_filter: str = ""
    id_min: int | None = None
    id_max: int | None = None
    reviewed_by_filter: str = ""
    confidence_min: float | None = None
    confidence_max: float | None = None
    sort_by: str = "id"
    sort_direction: str = "desc"


@dataclass(frozen=True, slots=True)
class LexiconSearchResult:
    rows: list[LexiconEntryRecord]
    total_rows: int
    filtered_rows: int
    counts_by_status: dict[str, int]
    available_categories: list[str]
    message: str
    lexicon_version: int | None = None
    updated_at: str | None = None
    status_filter: str = "all"
    limit: int = 100
    offset: int = 0
    category_filter: str = ""
    value_filter: str = ""
    source_filter: str = "all"
    request_filter: str = ""
    id_min: int | None = None
    id_max: int | None = None
    reviewed_by_filter: str = ""
    confidence_min: float | None = None
    confidence_max: float | None = None
    sort_by: str = "id"
    sort_direction: str = "desc"

    def to_table_rows(self) -> list[list[object]]:
        return [row.to_table_row() for row in self.rows]


@dataclass(frozen=True)
class LexiconUpdateRequest:
    entry_id: int
    status: str
    category: str
    value: str


@dataclass(frozen=True)
class LexiconDeleteRequest:
    entry_ids: list[int]


@dataclass(frozen=True)
class LexiconMutationResult:
    success: bool
    message: str
    affected_count: int = 0


@dataclass(frozen=True, slots=True)
class AssignmentRecord:
    id: int
    title: str
    content_original: str
    content_completed: str
    status: str = "PENDING"
    lexicon_coverage_percent: float = 0.0
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class AssignmentAudioRecord:
    id: int
    assignment_id: int
    audio_path: str
    audio_format: str
    voice: str
    style_preset: str
    duration_sec: float = 0.0
    sample_rate: int = 0
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class AssignmentSpeechSynthesisDTO:
    audio_path: str
    audio_format: str
    voice: str
    style_preset: str
    duration_sec: float = 0.0
    sample_rate: int = 0


@dataclass(frozen=True, slots=True)
class AssignmentLexiconMatch:
    entry_id: int
    term: str
    category: str
    source: str
    occurrences: int


@dataclass(frozen=True, slots=True)
class AssignmentMissingWord:
    term: str
    occurrences: int
    example_usage: str = ""


@dataclass(frozen=True, slots=True)
class AssignmentDiffChunk:
    operation: str
    original_text: str
    completed_text: str


@dataclass(frozen=True)
class AssignmentScanResultDTO:
    assignment_id: int | None
    title: str
    content_original: str
    content_completed: str
    word_count: int
    matches: list[AssignmentLexiconMatch]
    diff_chunks: list[AssignmentDiffChunk]
    duration_ms: float
    message: str
    missing_words: list[AssignmentMissingWord] = field(default_factory=list)
    known_token_count: int = 0
    unknown_token_count: int = 0
    lexicon_coverage_percent: float = 0.0
    assignment_status: str = "PENDING"


@dataclass(frozen=True, slots=True)
class QuickAddSuggestionDTO:
    term: str
    recommended_category: str
    candidate_categories: tuple[str, ...]
    confidence: float
    rationale: str
    suggested_example_usage: str = ""


@dataclass(frozen=True, slots=True)
class AssignmentBulkOperationResultDTO:
    operation: str
    requested_ids: tuple[int, ...]
    processed_ids: tuple[int, ...]
    failed_ids: tuple[int, ...]
    success_count: int
    failed_count: int
    message: str
    failure_details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AssignmentSpeechPlayerStateDTO:
    state: str
    position_sec: float = 0.0
    duration_sec: float = 0.0
    audio_path: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class AssignmentSpeechResultDTO:
    assignment_id: int
    audio_record: AssignmentAudioRecord | None
    player_state: AssignmentSpeechPlayerStateDTO
    message: str


@dataclass(frozen=True)
class ExportRequest:
    output_path: Path


@dataclass(frozen=True)
class ExportResult:
    success: bool
    message: str
    output_path: Path | None = None
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Result(Generic[T]):
    success: bool
    data: T | None = None
    error_message: str | None = None
    status_code: str = "ok"

    @classmethod
    def ok(cls, data: T, status_code: str = "ok") -> "Result[T]":
        return cls(success=True, data=data, error_message=None, status_code=status_code)

    @classmethod
    def fail(
        cls,
        error_message: str,
        *,
        status_code: str = "error",
        data: T | None = None,
    ) -> "Result[T]":
        return cls(
            success=False,
            data=data,
            error_message=str(error_message).strip() or "Unknown error.",
            status_code=status_code,
        )
