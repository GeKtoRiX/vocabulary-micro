from __future__ import annotations

from pathlib import Path
from unittest.mock import create_autospec
import pytest

from backend.python_services.core.domain import (
    CategoryMutationResult,
    ICategoryRepository,
    ILexiconRepository,
    LexiconEntryRecord,
    LexiconMutationResult,
    LexiconSearchResult,
)


@pytest.fixture
def sample_parse_payload() -> dict[str, object]:
    return {
        "tokens": [
            {
                "token": "Run",
                "normalized": "run",
                "lemma": "run",
                "pos": "VERB",
                "categories": ["Verb"],
                "match_source": "exact",
                "matched_form": "run",
                "bert_score": None,
            },
            {
                "token": "fast",
                "normalized": "fast",
                "lemma": "fast",
                "pos": "ADV",
                "categories": ["Adverb"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
        ],
        "stats": {
            "tokens_total": 2,
            "known_tokens": 1,
            "unknown_tokens": 1,
            "coverage_percent": 50.0,
            "source_counts": {"exact": 1, "none": 1},
        },
        "phrase_matches": [],
        "pipeline": {"status": "ok"},
        "stage_statuses": [],
        "pipeline_status": "ok",
    }


@pytest.fixture
def sample_lexicon_entry() -> LexiconEntryRecord:
    return LexiconEntryRecord(
        id=1,
        category="Verb",
        value="run",
        normalized="run",
        source="manual",
        confidence=1.0,
        first_seen_at="2026-01-01T00:00:00+00:00",
        request_id="req-1",
        status="approved",
        created_at="2026-01-01T00:00:00+00:00",
        reviewed_at=None,
        reviewed_by=None,
        review_note=None,
    )


@pytest.fixture
def sample_lexicon_search_result(sample_lexicon_entry: LexiconEntryRecord) -> LexiconSearchResult:
    return LexiconSearchResult(
        rows=[sample_lexicon_entry],
        total_rows=1,
        filtered_rows=1,
        counts_by_status={"approved": 1},
        available_categories=["Verb", "Noun"],
        message="Loaded 1 row(s).",
    )


@pytest.fixture
def sample_category_mutation_result() -> CategoryMutationResult:
    return CategoryMutationResult(
        categories=["Noun", "Verb", "Adjective"],
        message="Category updated.",
    )


@pytest.fixture
def mock_lexicon_repository() -> ILexiconRepository:
    repo = create_autospec(ILexiconRepository, instance=True)
    repo.parse_text.return_value = {"tokens": [], "stats": {}, "phrase_matches": []}
    repo.parse_mwe_text.return_value = {}
    repo.pipeline_status.return_value = {"status": "ok"}
    repo.detect_third_pass.return_value = {}
    repo.build_index.return_value = ({}, {})
    repo.add_entry.return_value = object()
    repo.add_entries.return_value = []
    repo.save.return_value = None
    repo.supports_mwe_upsert.return_value = True
    repo.upsert_mwe_expression.return_value = 1
    repo.upsert_mwe_sense.return_value = 1
    repo.search_entries.return_value = LexiconSearchResult(
        rows=[],
        total_rows=0,
        filtered_rows=0,
        counts_by_status={},
        available_categories=[],
        message="",
    )
    repo.get_entry.return_value = None
    repo.update_entry.return_value = LexiconMutationResult(success=True, message="ok", affected_count=1)
    repo.delete_entries.return_value = LexiconMutationResult(success=True, message="ok", affected_count=1)
    return repo


@pytest.fixture
def mock_category_repository() -> ICategoryRepository:
    repo = create_autospec(ICategoryRepository, instance=True)
    repo.list_categories.return_value = ["Noun", "Verb"]
    repo.create_category.return_value = CategoryMutationResult(
        categories=["Noun", "Verb", "Adjective"],
        message="Category created.",
    )
    repo.delete_category.return_value = CategoryMutationResult(
        categories=["Noun", "Verb"],
        message="Category deleted.",
    )
    return repo
