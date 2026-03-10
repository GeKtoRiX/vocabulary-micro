from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.domain import (
    CategoryMutationResult,
    ICategoryRepository,
    ILexiconRepository,
    LexiconDeleteRequest,
    LexiconEntryRecord,
    LexiconMutationResult,
    LexiconQuery,
    LexiconSearchResult,
    LexiconUpdateRequest,
)
from infrastructure.adapters.llm_third_pass import LlmThirdPassExtractor
from infrastructure.config import PipelineSettings
from infrastructure.sqlite import SqliteLexicon
from infrastructure.sqlite.management_store import SqliteLexiconManagementStore


class SqliteLexiconGateway(ILexiconRepository, ICategoryRepository):
    """Clean architecture adapter backed by SqliteLexicon and dedicated management store."""

    def __init__(
        self,
        db_path: Path,
        settings: PipelineSettings | None = None,
        *,
        third_pass_preflight: Callable[[], None] | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._settings = settings or PipelineSettings.from_env()
        self._store = SqliteLexicon(self._db_path, language="en", settings=self._settings)
        self._management = SqliteLexiconManagementStore(self._db_path)
        self._third_pass_extractor = LlmThirdPassExtractor(self._settings)
        self._third_pass_preflight = third_pass_preflight

    @property
    def db_path(self) -> Path:
        return self._db_path

    def parse_text(self, text: str, request_id: str | None = None) -> dict[str, Any]:
        return dict(self._store.parse_text(text, request_id=request_id))

    def parse_mwe_text(
        self,
        text: str,
        *,
        request_id: str | None = None,
        top_n: int = 3,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        return dict(
            self._store.parse_mwe_text(
                text,
                request_id=request_id,
                top_n=max(1, int(top_n)),
                enabled=enabled,
            )
        )

    def pipeline_status(self) -> dict[str, Any]:
        return dict(self._store.pipeline_status())

    def detect_third_pass(
        self,
        *,
        text: str,
        request_id: str,
        think_mode: bool | None = None,
        enabled: bool | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        if self._third_pass_preflight is not None:
            self._third_pass_preflight()
        return dict(
            self._third_pass_extractor.detect(
                text=text,
                request_id=request_id,
                think_mode=think_mode,
                enabled=enabled,
                timeout_ms=timeout_ms,
            )
        )

    def build_index(self) -> tuple[dict[str, list[str]], dict[tuple[str, ...], list[str]]]:
        return self._store.build_index()

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
        return self._store.add_entry(
            category=category,
            value=value,
            source=source,
            confidence=confidence,
            request_id=request_id,
            example_usage=example_usage,
        )

    def add_entries(
        self,
        entries: list[tuple[str, str]],
        *,
        source: str = "manual",
        confidence: float | None = None,
        request_id: str | None = None,
    ) -> list[object]:
        return list(
            self._store.add_entries(
                entries=entries,
                source=source,
                confidence=confidence,
                request_id=request_id,
            )
        )

    def save(self) -> object:
        return self._store.save()

    def supports_mwe_upsert(self) -> bool:
        return True

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
        return int(
            self._store.upsert_mwe_expression(
                canonical_form=canonical_form,
                expression_type=expression_type,
                is_separable=is_separable,
                max_gap_tokens=max_gap_tokens,
                base_lemma=base_lemma,
                particle=particle,
            )
        )

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
        return int(
            self._store.upsert_mwe_sense(
                expression_id=expression_id,
                sense_key=sense_key,
                gloss=gloss,
                usage_label=usage_label,
                example=example,
                priority=priority,
            )
        )

    def search_entries(self, query: LexiconQuery) -> LexiconSearchResult:
        return self._management.search_entries(query)

    def get_entry(self, entry_id: int) -> LexiconEntryRecord | None:
        return self._management.get_entry(entry_id)

    def update_entry(self, request: LexiconUpdateRequest) -> LexiconMutationResult:
        return self._management.update_entry(request)

    def delete_entries(self, request: LexiconDeleteRequest) -> LexiconMutationResult:
        return self._management.delete_entries(request)

    def get_statistics(self) -> dict[str, object]:
        return self._management.get_statistics()

    def list_categories(self) -> list[str]:
        return self._management.list_categories()

    def create_category(self, name: str) -> CategoryMutationResult:
        return self._management.create_category(name)

    def delete_category(self, name: str) -> CategoryMutationResult:
        return self._management.delete_category(name)

    def close(self) -> None:
        self._store.close()
