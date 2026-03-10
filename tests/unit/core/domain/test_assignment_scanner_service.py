from __future__ import annotations

from core.domain import LexiconEntryRecord, LexiconQuery, LexiconSearchResult, Result
from core.domain.services.assignment_scanner_service import AssignmentScannerService


class _StubLexiconSearchInteractor:
    def __init__(self, result: Result[LexiconSearchResult]) -> None:
        self._result = result
        self.calls: list[LexiconQuery] = []

    def search(self, query: LexiconQuery) -> Result[LexiconSearchResult]:
        self.calls.append(query)
        return self._result


def _entry(
    *,
    entry_id: int,
    value: str,
    category: str = "Verb",
    status: str = "approved",
) -> LexiconEntryRecord:
    normalized = str(value).strip().lower()
    return LexiconEntryRecord(
        id=entry_id,
        category=category,
        value=value,
        normalized=normalized,
        source="manual",
        confidence=1.0,
        first_seen_at="",
        request_id=None,
        status=status,
        created_at="",
        reviewed_at=None,
        reviewed_by=None,
        review_note=None,
    )


def test_scanner_uses_lexicon_search_and_builds_matches_and_diff() -> None:
    search_payload = LexiconSearchResult(
        rows=[
            _entry(entry_id=1, value="fill"),
            _entry(entry_id=2, value="fill in", category="Phrasal Verb"),
        ],
        total_rows=2,
        filtered_rows=2,
        counts_by_status={"approved": 2},
        available_categories=["Verb", "Phrasal Verb"],
        message="ok",
    )
    search_interactor = _StubLexiconSearchInteractor(Result.ok(search_payload))
    scanner = AssignmentScannerService(
        lexicon_search_interactor=search_interactor,
        search_limit=200,
    )

    result = scanner.scan(
        title="Unit Assignment",
        content_original="Please fill the report.",
        content_completed="Please fill in the report and fill in details.",
    )

    assert result.word_count > 0
    assert any(item.term == "fill in" and item.occurrences >= 2 for item in result.matches)
    assert any(chunk.operation in {"insert", "replace"} for chunk in result.diff_chunks)
    assert result.lexicon_coverage_percent > 0.0
    assert len(search_interactor.calls) == 1
    query = search_interactor.calls[0]
    assert query.status == "all"
    assert query.limit == 200


def test_scanner_counts_pending_review_as_known_and_excludes_rejected() -> None:
    search_payload = LexiconSearchResult(
        rows=[
            _entry(entry_id=1, value="fill in", category="Phrasal Verb", status="pending_review"),
            _entry(entry_id=2, value="report", category="Noun", status="rejected"),
        ],
        total_rows=2,
        filtered_rows=2,
        counts_by_status={"pending_review": 1, "rejected": 1},
        available_categories=["Phrasal Verb", "Noun"],
        message="ok",
    )
    search_interactor = _StubLexiconSearchInteractor(Result.ok(search_payload))
    scanner = AssignmentScannerService(
        lexicon_search_interactor=search_interactor,
        known_statuses=("approved", "pending_review"),
    )

    result = scanner.scan(
        content_original="",
        content_completed="Please fill in report.",
    )

    assert any(item.term == "fill in" for item in result.matches)
    assert all(item.term != "report" for item in result.matches)
    assert result.known_token_count == 2
    assert result.unknown_token_count == 2


def test_scanner_returns_diff_when_lexicon_search_fails() -> None:
    search_interactor = _StubLexiconSearchInteractor(
        Result.fail("db failed", status_code="db_failed")
    )
    scanner = AssignmentScannerService(lexicon_search_interactor=search_interactor)

    result = scanner.scan(
        content_original="alpha beta",
        content_completed="alpha gamma beta",
    )

    assert result.matches == []
    assert any(chunk.operation == "insert" for chunk in result.diff_chunks)
    assert any(item.term == "gamma" and item.example_usage for item in result.missing_words)
    assert result.unknown_token_count == 3
    assert "db failed" in result.message.lower()


def test_scanner_normalizes_plural_tokens_for_known_matches() -> None:
    search_payload = LexiconSearchResult(
        rows=[_entry(entry_id=1, value="student", category="Noun")],
        total_rows=1,
        filtered_rows=1,
        counts_by_status={"approved": 1},
        available_categories=["Noun"],
        message="ok",
    )
    search_interactor = _StubLexiconSearchInteractor(Result.ok(search_payload))
    scanner = AssignmentScannerService(lexicon_search_interactor=search_interactor)

    result = scanner.scan(
        content_original="",
        content_completed="Students read.",
    )

    assert any(item.term == "student" and item.occurrences == 1 for item in result.matches)
    assert all(item.term != "students" for item in result.missing_words)
    assert result.known_token_count == 1
    assert result.unknown_token_count == 1


def test_scanner_reports_plural_missing_words_in_normalized_form() -> None:
    search_payload = LexiconSearchResult(
        rows=[],
        total_rows=0,
        filtered_rows=0,
        counts_by_status={},
        available_categories=[],
        message="ok",
    )
    search_interactor = _StubLexiconSearchInteractor(Result.ok(search_payload))
    scanner = AssignmentScannerService(lexicon_search_interactor=search_interactor)

    result = scanner.scan(
        content_original="",
        content_completed="Students students.",
    )

    assert len(result.missing_words) == 1
    assert result.missing_words[0].term == "student"
    assert result.missing_words[0].occurrences == 2
