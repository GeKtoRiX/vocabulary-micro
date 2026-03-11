from __future__ import annotations

from pathlib import Path

from backend.python_services.core.domain import (
    LexiconEntryRecord,
    LexiconSearchResult,
    ParseRequest,
    PhraseMatchRecord,
    PipelineStats,
    Result,
    StageStatus,
    TokenRecord,
)


def test_parse_request_has_content_for_empty_and_non_empty_text() -> None:
    assert ParseRequest(text="hello world").has_content is True
    assert ParseRequest(text="   spaced   ").has_content is True
    assert ParseRequest(text="").has_content is False
    assert ParseRequest(text="   ").has_content is False


def test_token_record_to_dict_returns_detached_category_list() -> None:
    token = TokenRecord(
        token="run",
        normalized="run",
        lemma="run",
        pos="VERB",
        start=0,
        end=3,
        categories=["Verb"],
        known=True,
        match_source="exact",
        matched_form="run",
        bert_score=0.9,
    )

    payload = token.to_dict()
    payload["categories"].append("Injected")

    assert token.categories == ["Verb"]
    assert payload["categories"] == ["Verb", "Injected"]


def test_phrase_match_and_pipeline_stats_to_dict() -> None:
    phrase = PhraseMatchRecord(
        phrase="take off",
        normalized="take off",
        start_token_index=1,
        end_token_index=2,
        categories=("Phrasal Verb",),
    )
    stats = PipelineStats(
        tokens_total=10,
        known_tokens=7,
        unknown_tokens=3,
        coverage_percent=70.0,
        source_counts={"exact": 7, "none": 3},
    )

    phrase_payload = phrase.to_dict()
    stats_payload = stats.to_dict()

    assert phrase_payload["phrase"] == "take off"
    assert phrase_payload["categories"] == ["Phrasal Verb"]
    assert stats_payload["tokens_total"] == 10
    assert stats_payload["source_counts"] == {"exact": 7, "none": 3}


def test_stage_status_rounds_duration_and_copies_metadata() -> None:
    status = StageStatus(
        stage="tokenize",
        status="ok",
        duration_ms=12.34567,
        reason="",
        metadata={"batch": 1},
    )

    payload = status.to_dict()
    payload["metadata"]["batch"] = 99

    assert payload["duration_ms"] == 12.346
    assert status.metadata == {"batch": 1}


def test_lexicon_entry_record_to_table_row_keeps_defined_order() -> None:
    entry = LexiconEntryRecord(
        id=99,
        category="Noun",
        value="superlongvalue" * 100,
        normalized="superlongvalue" * 100,
        source="auto",
        confidence=None,
        first_seen_at=None,
        request_id=None,
        status="pending_review",
        created_at=None,
        reviewed_at=None,
        reviewed_by=None,
        review_note=None,
    )

    row = entry.to_table_row()

    assert row[0] == 99
    assert row[1] == "Noun"
    assert row[2] == "superlongvalue" * 100
    assert row[8] == "pending_review"


def test_lexicon_search_result_to_table_rows_maps_rows() -> None:
    rows = [
        LexiconEntryRecord(
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
        ),
    ]
    result = LexiconSearchResult(
        rows=rows,
        total_rows=1,
        filtered_rows=1,
        counts_by_status={"approved": 1},
        available_categories=["Verb"],
        message="Loaded.",
    )

    table_rows = result.to_table_rows()

    assert table_rows == [rows[0].to_table_row()]


def test_result_ok_and_fail_factories_normalize_messages() -> None:
    ok_result = Result.ok(data={"value": 1})
    fail_result = Result.fail("  bad request  ")
    empty_fail_result = Result.fail("")

    assert ok_result.success is True
    assert ok_result.status_code == "ok"
    assert ok_result.data == {"value": 1}

    assert fail_result.success is False
    assert fail_result.status_code == "error"
    assert fail_result.error_message == "bad request"

    assert empty_fail_result.error_message == "Unknown error."


def test_path_value_object_supports_path_types() -> None:
    path = Path("output.xlsx")
    assert path.suffix == ".xlsx"
