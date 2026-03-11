from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.python_services.core.domain import (
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
from backend.python_services.infrastructure.adapters.llm_third_pass import LlmThirdPassExtractor
from backend.python_services.infrastructure.config import PipelineSettings
from backend.python_services.infrastructure.nlp.lexicon_engine import LexiconEngine
from backend.python_services.infrastructure.nlp.mwe_index_provider import MweIndexProvider
from backend.python_services.infrastructure.nlp.mwe_second_pass_engine import MweSecondPassEngine
from backend.python_services.infrastructure.nlp.table_models import LexiconEntry


@dataclass(frozen=True)
class _SnapshotCache:
    fetched_at: float
    payload: dict[str, Any]


class _HttpLexiconSnapshotClient:
    def __init__(self, *, base_url: str, timeout_sec: float = 30.0, cache_ttl_sec: float = 0.25) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = max(0.2, float(timeout_sec))
        self._cache_ttl_sec = max(0.0, float(cache_ttl_sec))
        self._snapshot_cache: _SnapshotCache | None = None

    def invalidate(self) -> None:
        self._snapshot_cache = None

    def lexicon_snapshot(self) -> dict[str, Any]:
        cached = self._snapshot_cache
        now = time.monotonic()
        if cached is not None and (now - cached.fetched_at) <= self._cache_ttl_sec:
            return cached.payload
        payload = self._request_json("/internal/v1/lexicon/export-snapshot")
        if not isinstance(payload, dict):
            raise ValueError("lexicon export snapshot must be an object")
        self._snapshot_cache = _SnapshotCache(fetched_at=now, payload=payload)
        return payload

    def lexicon_entries(self) -> list[LexiconEntry]:
        rows = self._table_rows("lexicon_entries")
        items: list[LexiconEntry] = []
        for row in rows:
            value = str(row.get("value", "")).strip()
            category = str(row.get("category", "")).strip()
            normalized = str(row.get("normalized", "")).strip()
            status = str(row.get("status", "")).strip().lower()
            if not value or not category or status == "rejected":
                continue
            items.append(
                LexiconEntry(
                    row=int(row.get("id", 0) or 0),
                    column=1,
                    category=category,
                    value=value or normalized,
                )
            )
        return items

    def lexicon_version(self) -> int:
        rows = self._table_rows("lexicon_meta")
        if not rows:
            return 0
        return int(rows[0].get("lexicon_version", 0) or 0)

    def mwe_version(self) -> int:
        rows = self._table_rows("mwe_meta")
        if not rows:
            return 0
        return int(rows[0].get("mwe_version", 0) or 0)

    def mwe_expressions(self) -> list[dict[str, object]]:
        rows = self._table_rows("mwe_expressions")
        return [
            {
                "id": int(row.get("id", 0) or 0),
                "canonical_form": str(row.get("canonical_form", "")).strip(),
                "expression_type": str(row.get("expression_type", "")).strip(),
                "base_lemma": str(row.get("base_lemma", "")).strip(),
                "particle": str(row.get("particle", "")).strip(),
                "is_separable": int(row.get("is_separable", 0) or 0),
                "max_gap_tokens": int(row.get("max_gap_tokens", 4) or 4),
            }
            for row in rows
            if str(row.get("canonical_form", "")).strip()
        ]

    def mwe_senses(self) -> list[dict[str, object]]:
        rows = self._table_rows("mwe_senses")
        return [
            {
                "id": int(row.get("id", 0) or 0),
                "expression_id": int(row.get("expression_id", 0) or 0),
                "sense_key": str(row.get("sense_key", "")).strip(),
                "gloss": str(row.get("gloss", "")).strip(),
                "usage_label": str(row.get("usage_label", "")).strip(),
                "example": str(row.get("example", "")).strip(),
                "priority": int(row.get("priority", 0) or 0),
            }
            for row in rows
            if int(row.get("expression_id", 0) or 0) > 0
        ]

    def mwe_embeddings(self, model_name: str, model_revision: str | None) -> dict[int, tuple[float, ...]]:
        del model_name, model_revision
        return {}

    def build_index(self) -> tuple[dict[str, list[str]], dict[tuple[str, ...], list[str]]]:
        payload = self._request_json("/internal/v1/lexicon/index")
        if not isinstance(payload, dict):
            raise ValueError("lexicon index payload must be an object")
        single_word = {
            str(key): [str(item) for item in value]
            for key, value in dict(payload.get("single_word_index", {})).items()
            if isinstance(value, list)
        }
        multi_word = {
            tuple(part for part in str(key).split(" ") if part): [str(item) for item in value]
            for key, value in dict(payload.get("multi_word_index", {})).items()
            if isinstance(value, list)
        }
        return single_word, multi_word

    def list_categories(self) -> list[str]:
        payload = self._request_json("/internal/v1/lexicon/categories")
        if not isinstance(payload, dict):
            raise ValueError("categories payload must be an object")
        categories = payload.get("categories", [])
        if not isinstance(categories, list):
            return []
        return [str(item).strip() for item in categories if str(item).strip()]

    def create_category(self, name: str) -> CategoryMutationResult:
        payload = self._request_json(
            "/internal/v1/lexicon/categories",
            method="POST",
            body={"name": name},
        )
        return CategoryMutationResult(
            categories=[str(item).strip() for item in payload.get("categories", []) if str(item).strip()],
            message=str(payload.get("message", "")).strip(),
        )

    def add_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request_json("/internal/v1/lexicon/entries", method="POST", body=payload)
        self.invalidate()
        return response

    def add_entries(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request_json("/internal/v1/lexicon/entries/bulk", method="POST", body=payload)
        self.invalidate()
        return response

    def upsert_mwe_expression(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request_json("/internal/v1/lexicon/mwe/expression", method="POST", body=payload)
        self.invalidate()
        return response

    def upsert_mwe_sense(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request_json("/internal/v1/lexicon/mwe/sense", method="POST", body=payload)
        self.invalidate()
        return response

    def search(self, query: LexiconQuery) -> dict[str, Any]:
        params = {
            "status": query.status,
            "limit": query.limit,
            "offset": query.offset,
            "category_filter": query.category_filter,
            "value_filter": query.value_filter,
            "source_filter": query.source_filter,
            "request_filter": query.request_filter,
            "id_min": query.id_min,
            "id_max": query.id_max,
            "reviewed_by_filter": query.reviewed_by_filter,
            "confidence_min": query.confidence_min,
            "confidence_max": query.confidence_max,
            "sort_by": query.sort_by,
            "sort_direction": query.sort_direction,
            "semantic_raw_query": query.semantic_raw_query,
        }
        return self._request_json("/internal/v1/lexicon/search", query=params)

    def statistics(self) -> dict[str, Any]:
        return self._request_json("/internal/v1/lexicon/statistics")

    def _table_rows(self, table_name: str) -> list[dict[str, Any]]:
        snapshot = self.lexicon_snapshot()
        tables = snapshot.get("tables", [])
        if not isinstance(tables, list):
            return []
        for table in tables:
            if not isinstance(table, dict) or str(table.get("name", "")).strip() != table_name:
                continue
            columns = table.get("columns", [])
            rows = table.get("rows", [])
            if not isinstance(columns, list) or not isinstance(rows, list):
                return []
            result: list[dict[str, Any]] = []
            for raw_row in rows:
                if not isinstance(raw_row, list):
                    continue
                result.append({str(column): raw_row[idx] if idx < len(raw_row) else None for idx, column in enumerate(columns)})
            return result
        return []

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        if query:
            query_params = {
                key: value
                for key, value in query.items()
                if value is not None and value != ""
            }
            if query_params:
                url = f"{url}?{urlencode(query_params, doseq=True)}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url=url, data=data, headers=headers, method=method)
        with urlopen(request, timeout=self._timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path} response must be a JSON object")
        return payload


class _HttpLexiconEngine(LexiconEngine):
    def __init__(self, *, settings: PipelineSettings, snapshot_client: _HttpLexiconSnapshotClient) -> None:
        super().__init__(language="en", settings=settings)
        self._snapshot_client = snapshot_client
        self._request_doc_cache: OrderedDict[str, tuple[str, object]] = OrderedDict()
        self._request_doc_cache_limit = 32

    def iter_entries(self) -> list[LexiconEntry]:
        return self._snapshot_client.lexicon_entries()

    def get_lexicon_version(self) -> int:
        return self._snapshot_client.lexicon_version()

    def _cache_request_doc(self, *, request_id: str, text: str, doc: object) -> None:
        if not request_id:
            return
        self._request_doc_cache[request_id] = (text, doc)
        self._request_doc_cache.move_to_end(request_id)
        while len(self._request_doc_cache) > self._request_doc_cache_limit:
            self._request_doc_cache.popitem(last=False)

    def pop_cached_request_doc(self, *, request_id: str, text: str) -> object | None:
        cached = self._request_doc_cache.pop(request_id, None)
        if cached is None:
            return None
        cached_text, cached_doc = cached
        if cached_text != text:
            return None
        return cached_doc

    def release_request_resources(self, request_id: str | None) -> None:
        normalized = str(request_id or "").strip()
        if normalized:
            self._request_doc_cache.pop(normalized, None)


class HttpLexiconGateway(ILexiconRepository, ICategoryRepository):
    """Hybrid gateway: local NLP capability engine plus lexicon owner-service over HTTP."""

    def __init__(
        self,
        *,
        base_url: str,
        settings: PipelineSettings | None = None,
        timeout_sec: float = 30.0,
        snapshot_cache_ttl_sec: float = 0.25,
        third_pass_preflight=None,
    ) -> None:
        self._settings = settings or PipelineSettings.from_env()
        self._snapshot_client = _HttpLexiconSnapshotClient(
            base_url=base_url,
            timeout_sec=timeout_sec,
            cache_ttl_sec=snapshot_cache_ttl_sec,
        )
        self._engine = _HttpLexiconEngine(settings=self._settings, snapshot_client=self._snapshot_client)
        self._mwe_index_provider = MweIndexProvider(
            version_loader=self._snapshot_client.mwe_version,
            expression_loader=self._snapshot_client.mwe_expressions,
            sense_loader=self._snapshot_client.mwe_senses,
            embedding_loader=self._snapshot_client.mwe_embeddings,
        )
        self._mwe_second_pass_engine = MweSecondPassEngine(
            settings=self._settings,
            index_provider=self._mwe_index_provider,
        )
        self._third_pass_extractor = LlmThirdPassExtractor(self._settings)
        self._third_pass_preflight = third_pass_preflight

    def parse_text(self, text: str, request_id: str | None = None) -> dict[str, Any]:
        return dict(self._engine.parse_text(text, request_id=request_id))

    def parse_mwe_text(
        self,
        text: str,
        *,
        request_id: str | None = None,
        top_n: int = 3,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        preparsed_doc = None
        if request_id:
            preparsed_doc = self._engine.pop_cached_request_doc(request_id=request_id, text=text)
        try:
            return dict(
                self._mwe_second_pass_engine.parse(
                    text,
                    request_id=request_id,
                    top_n=max(1, int(top_n)),
                    enabled=enabled,
                    preparsed_doc=preparsed_doc,
                )
            )
        finally:
            self.release_request_resources(request_id=request_id)

    def pipeline_status(self) -> dict[str, Any]:
        return dict(self._engine.pipeline_status())

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
        return self._snapshot_client.build_index()

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
        del example_usage
        return self._snapshot_client.add_entry(
            {
                "category": category,
                "value": value,
                "source": source,
                "confidence": confidence,
                "request_id": request_id,
            }
        )

    def add_entries(
        self,
        entries: list[tuple[str, str]],
        *,
        source: str = "manual",
        confidence: float | None = None,
        request_id: str | None = None,
    ) -> list[object]:
        payload = self._snapshot_client.add_entries(
            {
                "entries": [{"category": category, "value": value} for category, value in entries],
                "source": source,
                "confidence": confidence,
                "request_id": request_id,
            }
        )
        inserted_count = int(payload.get("inserted_count", 0) or 0)
        return [payload] * max(0, inserted_count)

    def save(self) -> object:
        return None

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
        payload = self._snapshot_client.upsert_mwe_expression(
            {
                "canonical_form": canonical_form,
                "expression_type": expression_type,
                "is_separable": bool(is_separable),
                "max_gap_tokens": int(max_gap_tokens),
                "base_lemma": base_lemma,
                "particle": particle,
            }
        )
        self._mwe_index_provider.invalidate()
        return int(payload.get("expression_id", 0) or 0)

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
        payload = self._snapshot_client.upsert_mwe_sense(
            {
                "expression_id": int(expression_id),
                "sense_key": sense_key,
                "gloss": gloss,
                "usage_label": usage_label,
                "example": example,
                "priority": int(priority),
            }
        )
        self._mwe_index_provider.invalidate()
        return int(payload.get("sense_id", 0) or 0)

    def search_entries(self, query: LexiconQuery) -> LexiconSearchResult:
        payload = self._snapshot_client.search(query)
        rows_payload = payload.get("rows", [])
        rows = [
            LexiconEntryRecord(
                id=int(row.get("id", 0) or 0),
                category=str(row.get("category", "")).strip(),
                value=str(row.get("value", "")).strip(),
                normalized=str(row.get("normalized", "")).strip(),
                source=str(row.get("source", "")).strip(),
                confidence=(float(row["confidence"]) if row.get("confidence") is not None else None),
                first_seen_at=(str(row["first_seen_at"]) if row.get("first_seen_at") is not None else None),
                request_id=(str(row["request_id"]) if row.get("request_id") is not None else None),
                status=str(row.get("status", "")).strip(),
                created_at=(str(row["created_at"]) if row.get("created_at") is not None else None),
                reviewed_at=(str(row["reviewed_at"]) if row.get("reviewed_at") is not None else None),
                reviewed_by=(str(row["reviewed_by"]) if row.get("reviewed_by") is not None else None),
                review_note=(str(row["review_note"]) if row.get("review_note") is not None else None),
            )
            for row in rows_payload
            if isinstance(row, dict)
        ]
        counts_by_status = {
            str(key): int(value or 0)
            for key, value in dict(payload.get("counts_by_status", {})).items()
        }
        available_categories = [str(item).strip() for item in payload.get("available_categories", []) if str(item).strip()]
        return LexiconSearchResult(
            rows=rows,
            total_rows=int(payload.get("total_rows", 0) or 0),
            filtered_rows=int(payload.get("filtered_rows", 0) or 0),
            counts_by_status=counts_by_status,
            available_categories=available_categories,
            message=str(payload.get("message", "")).strip(),
            status_filter=query.status,
            limit=query.limit,
            offset=query.offset,
            category_filter=query.category_filter,
            value_filter=query.value_filter,
            source_filter=query.source_filter,
            request_filter=query.request_filter,
            id_min=query.id_min,
            id_max=query.id_max,
            reviewed_by_filter=query.reviewed_by_filter,
            confidence_min=query.confidence_min,
            confidence_max=query.confidence_max,
            sort_by=query.sort_by,
            sort_direction=query.sort_direction,
        )

    def get_entry(self, entry_id: int) -> LexiconEntryRecord | None:
        result = self.search_entries(LexiconQuery(status="all", limit=1, offset=0, id_min=entry_id, id_max=entry_id))
        return result.rows[0] if result.rows else None

    def update_entry(self, request: LexiconUpdateRequest) -> LexiconMutationResult:
        raise NotImplementedError("HttpLexiconGateway.update_entry is not required by nlp-service")

    def delete_entries(self, request: LexiconDeleteRequest) -> LexiconMutationResult:
        raise NotImplementedError("HttpLexiconGateway.delete_entries is not required by nlp-service")

    def get_statistics(self) -> dict[str, Any]:
        return self._snapshot_client.statistics()

    def list_categories(self) -> list[str]:
        return self._snapshot_client.list_categories()

    def create_category(self, name: str) -> CategoryMutationResult:
        return self._snapshot_client.create_category(name)

    def delete_category(self, name: str) -> CategoryMutationResult:
        raise NotImplementedError("HttpLexiconGateway.delete_category is not required by nlp-service")

    def release_request_resources(self, *, request_id: str | None) -> None:
        self._engine.release_request_resources(request_id)
        self._mwe_second_pass_engine.release_request_resources(request_id)
