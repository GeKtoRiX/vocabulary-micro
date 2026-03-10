from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import (
    LexiconDeleteRequest,
    LexiconEntryRecord,
    LexiconMutationResult,
    LexiconQuery,
    LexiconSearchResult,
    LexiconUpdateRequest,
)


class ILexiconRepository(ABC):
    @abstractmethod
    def parse_text(self, text: str, request_id: str | None = None) -> dict[str, Any]:
        """Run first-pass parse pipeline and return token/summary payload."""

    @abstractmethod
    def parse_mwe_text(
        self,
        text: str,
        *,
        request_id: str | None = None,
        top_n: int = 3,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Run second-pass MWE/WSD parser and return occurrences payload."""

    @abstractmethod
    def pipeline_status(self) -> dict[str, Any]:
        """Return parser pipeline availability and configuration metadata."""

    @abstractmethod
    def detect_third_pass(
        self,
        *,
        text: str,
        request_id: str,
        think_mode: bool | None = None,
        enabled: bool | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Run third-pass LLM extraction and return normalized summary payload."""

    @abstractmethod
    def build_index(self) -> tuple[dict[str, list[str]], dict[tuple[str, ...], list[str]]]:
        """Load normalized single-word and multi-word indexes."""

    @abstractmethod
    def add_entry(
        self,
        category: str,
        value: str,
        *,
        source: str = "manual",
        confidence: float | None = None,
        request_id: str | None = None,
        example_usage: str | None = None,
    ) -> object:
        """Insert a single lexicon entry."""

    @abstractmethod
    def add_entries(
        self,
        entries: list[tuple[str, str]],
        *,
        source: str = "manual",
        confidence: float | None = None,
        request_id: str | None = None,
    ) -> list[object]:
        """Insert multiple lexicon entries."""

    @abstractmethod
    def save(self) -> object:
        """Flush persistence state after write operations."""

    @abstractmethod
    def supports_mwe_upsert(self) -> bool:
        """Return whether MWE upsert APIs are available."""

    @abstractmethod
    def upsert_mwe_expression(
        self,
        *,
        canonical_form: str,
        expression_type: str,
        is_separable: bool = False,
        max_gap_tokens: int = 4,
        base_lemma: str | None = None,
        particle: str | None = None,
    ) -> int:
        """Upsert MWE expression and return expression id."""

    @abstractmethod
    def upsert_mwe_sense(
        self,
        *,
        expression_id: int,
        sense_key: str,
        gloss: str,
        usage_label: str,
        example: str = "",
        priority: int = 0,
    ) -> int:
        """Upsert MWE sense and return sense id."""

    @abstractmethod
    def search_entries(self, query: LexiconQuery) -> LexiconSearchResult:
        """Load lexicon entries using filters, sorting, and pagination."""

    @abstractmethod
    def get_entry(self, entry_id: int) -> LexiconEntryRecord | None:
        """Fetch a single lexicon entry by id."""

    @abstractmethod
    def update_entry(self, request: LexiconUpdateRequest) -> LexiconMutationResult:
        """Update status/category/value of an existing lexicon entry."""

    @abstractmethod
    def delete_entries(self, request: LexiconDeleteRequest) -> LexiconMutationResult:
        """Delete one or more lexicon entries."""

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Return aggregate statistics: total count, counts_by_status, counts_by_source, categories."""
