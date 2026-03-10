from __future__ import annotations

from core.domain import (
    AssignmentDiffChunk,
    AssignmentLexiconMatch,
    AssignmentMissingWord,
    AssignmentRecord,
    AssignmentScanResultDTO,
    ParseAndSyncResultDTO,
    ParseRowSyncResultDTO,
    Result,
)
from core.use_cases.manage_assignments import ManageAssignmentsInteractor


class _StubAssignmentRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str]] = []
        self.updated: list[tuple[int, str, float | None]] = []
        self._next_id = 7
        self._records: dict[int, AssignmentRecord] = {
            3: AssignmentRecord(
                id=3,
                title="Sample",
                content_original="a",
                content_completed="b",
                status="PENDING",
                lexicon_coverage_percent=42.0,
                created_at="2026-03-01T00:00:00+00:00",
                updated_at="2026-03-01T00:00:00+00:00",
            )
        }

    def save_assignment(
        self,
        *,
        title: str,
        content_original: str,
        content_completed: str,
    ) -> AssignmentRecord:
        self.saved.append((title, content_original, content_completed))
        record = AssignmentRecord(
            id=self._next_id,
            title=title,
            content_original=content_original,
            content_completed=content_completed,
            status="PENDING",
            lexicon_coverage_percent=0.0,
            created_at="2026-03-01T00:00:00+00:00",
            updated_at="2026-03-01T00:00:00+00:00",
        )
        self._records[int(record.id)] = record
        self._next_id += 1
        return record

    def list_assignments(self, *, limit: int = 50, offset: int = 0) -> list[AssignmentRecord]:
        rows = sorted(self._records.values(), key=lambda item: int(item.id), reverse=True)
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        return rows[start:end]

    def get_assignment(self, *, assignment_id: int) -> AssignmentRecord | None:
        return self._records.get(int(assignment_id))

    def update_assignment_content(
        self,
        *,
        assignment_id: int,
        title: str,
        content_original: str,
        content_completed: str,
    ) -> AssignmentRecord | None:
        current = self._records.get(int(assignment_id))
        if current is None:
            return None
        updated = AssignmentRecord(
            id=current.id,
            title=title,
            content_original=content_original,
            content_completed=content_completed,
            status=current.status,
            lexicon_coverage_percent=current.lexicon_coverage_percent,
            created_at=current.created_at,
            updated_at="2026-03-01T00:00:00+00:00",
        )
        self._records[int(updated.id)] = updated
        return updated

    def delete_assignment(self, *, assignment_id: int) -> bool:
        safe_id = int(assignment_id)
        if safe_id not in self._records:
            return False
        del self._records[safe_id]
        return True

    def update_assignment_status(
        self,
        *,
        assignment_id: int,
        status: str,
        lexicon_coverage_percent: float | None = None,
    ) -> AssignmentRecord | None:
        self.updated.append((assignment_id, status, lexicon_coverage_percent))
        current = self._records.get(int(assignment_id))
        if current is None:
            return None
        updated = AssignmentRecord(
            id=current.id,
            title=current.title,
            content_original=current.content_original,
            content_completed=current.content_completed,
            status=status,
            lexicon_coverage_percent=float(lexicon_coverage_percent or 0.0),
            created_at=current.created_at,
            updated_at="2026-03-01T00:00:00+00:00",
        )
        self._records[int(updated.id)] = updated
        return updated

    def bulk_delete_assignments(self, *, ids: list[int]) -> tuple[list[int], list[int]]:
        deleted: list[int] = []
        not_found: list[int] = []
        for i in ids:
            safe_id = int(i)
            if safe_id in self._records:
                del self._records[safe_id]
                deleted.append(safe_id)
            else:
                not_found.append(safe_id)
        return deleted, not_found

    def get_assignment_coverage_stats(self) -> list[dict[str, object]]:
        return [
            {
                "title": r.title,
                "coverage_pct": r.lexicon_coverage_percent,
                "created_at": r.created_at,
            }
            for r in sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)
        ]


class _StubAssignmentSyncUseCase:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute(
        self,
        text: str,
        *,
        sync: bool | None = None,
        third_pass_enabled: bool | None = None,
        think_mode: bool | None = None,
    ) -> Result[ParseAndSyncResultDTO]:
        self.calls.append(
            {
                "text": text,
                "sync": sync,
                "third_pass_enabled": third_pass_enabled,
                "think_mode": think_mode,
            }
        )
        return Result.ok(
            ParseAndSyncResultDTO(
                table=[],
                summary={"sync_message": "ok"},
                status_message="synced",
                error_message="",
            )
        )


class _StubLexiconRepository:
    def __init__(self) -> None:
        self.added: list[dict[str, object]] = []

    def build_index(self):  # noqa: ANN001
        return ({}, {})

    def add_entry(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        self.added.append(dict(kwargs))
        return object()

    def save(self):
        return None


class _StubScanner:
    def scan(
        self,
        *,
        content_completed: str,
        content_original: str = "",
        title: str = "",
    ) -> AssignmentScanResultDTO:
        return AssignmentScanResultDTO(
            assignment_id=None,
            title=title,
            content_original=content_original,
            content_completed=content_completed,
            word_count=5,
            matches=[
                AssignmentLexiconMatch(
                    entry_id=1,
                    term="fill in",
                    category="Phrasal Verb",
                    source="manual",
                    occurrences=2,
                )
            ],
            diff_chunks=[
                AssignmentDiffChunk(operation="insert", original_text="", completed_text="fill in")
            ],
            duration_ms=12.3,
            message="ok",
            missing_words=[
                AssignmentMissingWord(
                    term="details",
                    occurrences=1,
                    example_usage="Please fill in details.",
                )
            ],
            known_token_count=4,
            unknown_token_count=1,
            lexicon_coverage_percent=80.0,
        )


class _CapturingLogger:
    def __init__(self) -> None:
        self.info_messages: list[str] = []
        self.error_messages: list[str] = []

    def info(self, message: str) -> None:
        self.info_messages.append(str(message))

    def error(self, message: str) -> None:
        self.error_messages.append(str(message))


def test_scan_and_save_returns_payload_with_assignment_id() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        completed_threshold_percent=70.0,
    )

    result = interactor.scan_and_save(
        title="A1",
        content_original="Please fill report",
        content_completed="Please fill in report",
    )

    assert result.success is True
    assert result.data is not None
    assert result.data.assignment_id == 7
    assert result.data.title == "A1"
    assert len(result.data.matches) == 1
    assert result.data.assignment_status == "COMPLETED"


def test_scan_and_save_rejects_empty_completed_text() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )

    result = interactor.scan_and_save(
        title="A1",
        content_original="x",
        content_completed="   ",
    )

    assert result.success is False
    assert result.status_code == "assignment_empty_completed_text"


def test_list_assignments_returns_repository_rows() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )

    result = interactor.list_assignments(limit=10, offset=0)

    assert result.success is True
    assert isinstance(result.data, list)
    assert result.data[0].title == "Sample"


def test_quick_add_missing_word_returns_added_payload() -> None:
    repository = _StubLexiconRepository()

    class _StubSentenceExtractor:
        def extract_sentence(self, *, text: str, term: str) -> str:
            _ = (text, term)
            return "Please fill in details."

    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=repository,
        sentence_extractor=_StubSentenceExtractor(),
    )

    result = interactor.quick_add_missing_word(
        assignment_id=7,
        term="details",
        content_completed="Please fill in details.",
        category="Auto Added",
    )

    assert result.success is True
    assert isinstance(result.data, ParseRowSyncResultDTO)
    assert result.data.status == "added"
    assert repository.added[0]["example_usage"] == "Please fill in details."


def test_quick_add_missing_word_rejects_stopword_for_auto_added_category() -> None:
    repository = _StubLexiconRepository()
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=repository,
    )

    result = interactor.quick_add_missing_word(
        assignment_id=7,
        term="the",
        content_completed="the quick brown fox",
        category="Auto Added",
    )

    assert result.success is False
    assert result.status_code == "assignment_quick_add_rejected"
    assert result.data is not None
    assert result.data.status == "rejected"
    assert repository.added == []


def test_suggest_quick_add_recommends_phrasal_verb_for_particle_tail_phrase() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )

    result = interactor.suggest_quick_add(
        term="look up",
        content_completed="Please look up the word in dictionary.",
        available_categories=["Verb", "Phrasal Verb", "Auto Added"],
    )

    assert result.success is True
    assert result.data is not None
    assert result.data.recommended_category == "Phrasal Verb"
    assert "Phrasal Verb" in result.data.candidate_categories
    assert result.data.confidence >= 0.8


def test_bulk_delete_assignments_reports_partial_success() -> None:
    repository = _StubAssignmentRepository()
    interactor = ManageAssignmentsInteractor(
        assignment_repository=repository,
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )

    result = interactor.bulk_delete_assignments(assignment_ids=[3, 999])

    assert result.success is True
    assert result.status_code == "assignment_bulk_delete_partial"
    assert result.data is not None
    assert result.data.success_count == 1
    assert result.data.failed_count == 1
    assert result.data.processed_ids == (3,)
    assert result.data.failed_ids == (999,)
    assert repository.get_assignment(assignment_id=3) is None


def test_bulk_rescan_assignments_reports_partial_success_and_syncs_existing_rows() -> None:
    sync_use_case = _StubAssignmentSyncUseCase()
    repository = _StubAssignmentRepository()
    interactor = ManageAssignmentsInteractor(
        assignment_repository=repository,
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        assignment_sync_use_case=sync_use_case,
    )

    result = interactor.bulk_rescan_assignments(assignment_ids=[3, 777])

    assert result.success is True
    assert result.status_code == "assignment_bulk_rescan_partial"
    assert result.data is not None
    assert result.data.success_count == 1
    assert result.data.failed_count == 1
    assert result.data.processed_ids == (3,)
    assert result.data.failed_ids == (777,)
    assert len(sync_use_case.calls) == 1
    assert sync_use_case.calls[0]["text"] == "b"


def test_scan_and_save_triggers_assignment_sync_pipeline() -> None:
    sync_use_case = _StubAssignmentSyncUseCase()
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        assignment_sync_use_case=sync_use_case,
    )

    result = interactor.scan_and_save(
        title="A2",
        content_original="Please fill report",
        content_completed="Please fill in report",
    )

    assert result.success is True
    assert len(sync_use_case.calls) == 1
    call = sync_use_case.calls[0]
    assert call["sync"] is True
    assert call["third_pass_enabled"] is True
    assert call["think_mode"] is False
    assert call["text"] == "Please fill in report"


def test_update_assignment_recalculates_scan_and_status() -> None:
    repository = _StubAssignmentRepository()
    interactor = ManageAssignmentsInteractor(
        assignment_repository=repository,
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        completed_threshold_percent=70.0,
    )

    result = interactor.update_assignment(
        assignment_id=3,
        title="Updated",
        content_original="Please fill report",
        content_completed="Please fill in report",
    )

    assert result.success is True
    assert result.data is not None
    assert result.data.assignment_id == 3
    assert result.data.title == "Updated"
    assert result.data.assignment_status == "COMPLETED"
    assert repository.get_assignment(assignment_id=3) is not None


def test_delete_assignment_returns_success_when_row_exists() -> None:
    repository = _StubAssignmentRepository()
    interactor = ManageAssignmentsInteractor(
        assignment_repository=repository,
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )

    result = interactor.delete_assignment(assignment_id=3)

    assert result.success is True
    assert result.data is True
    assert repository.get_assignment(assignment_id=3) is None


def test_scan_and_save_runs_sync_before_scan() -> None:
    events: list[str] = []

    class _OrderScanner:
        def scan(
            self,
            *,
            content_completed: str,
            content_original: str = "",
            title: str = "",
        ) -> AssignmentScanResultDTO:
            _ = (content_completed, content_original, title)
            events.append("scan")
            return AssignmentScanResultDTO(
                assignment_id=None,
                title=title,
                content_original=content_original,
                content_completed=content_completed,
                word_count=3,
                matches=[],
                diff_chunks=[],
                duration_ms=1.0,
                message="ok",
                missing_words=[],
                known_token_count=0,
                unknown_token_count=3,
                lexicon_coverage_percent=0.0,
            )

    class _OrderSyncUseCase:
        def execute(
            self,
            text: str,
            *,
            sync: bool | None = None,
            third_pass_enabled: bool | None = None,
            think_mode: bool | None = None,
        ) -> Result[ParseAndSyncResultDTO]:
            _ = (text, sync, third_pass_enabled, think_mode)
            events.append("sync")
            return Result.ok(
                ParseAndSyncResultDTO(
                    table=[],
                    summary={"sync_message": "ok"},
                    status_message="synced",
                    error_message="",
                )
            )

    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_OrderScanner(),
        lexicon_repository=_StubLexiconRepository(),
        assignment_sync_use_case=_OrderSyncUseCase(),
    )

    result = interactor.scan_and_save(
        title="A3",
        content_original="orig",
        content_completed="completed",
    )

    assert result.success is True
    assert events[:2] == ["sync", "scan"]


def test_scan_and_save_recomputes_coverage_in_same_call_after_sync() -> None:
    class _StatefulLexiconRepository:
        def __init__(self) -> None:
            self._single: dict[str, list[str]] = {}
            self._multi: dict[tuple[str, ...], list[str]] = {}

        def build_index(self):  # noqa: ANN001
            return self._single, self._multi

        def add_phrase(self, value: str, category: str) -> None:
            key = tuple(item for item in value.split() if item)
            self._multi[key] = [category]

        def add_entry(self, *args, **kwargs):  # noqa: ANN002, ANN003
            _ = args
            value = str(kwargs.get("value", "")).strip().lower()
            category = str(kwargs.get("category", "Auto Added")).strip() or "Auto Added"
            if not value:
                return object()
            if " " in value:
                self.add_phrase(value=value, category=category)
            else:
                self._single[value] = [category]
            return object()

        def save(self):
            return None

    class _CoverageScanner:
        def __init__(self, lexicon_repository: _StatefulLexiconRepository) -> None:
            self._lexicon_repository = lexicon_repository

        def scan(
            self,
            *,
            content_completed: str,
            content_original: str = "",
            title: str = "",
        ) -> AssignmentScanResultDTO:
            _ = (content_completed, content_original)
            _, multi_word = self._lexicon_repository.build_index()
            has_fill_in = ("fill", "in") in multi_word
            coverage = 100.0 if has_fill_in else 0.0
            matches = (
                [
                    AssignmentLexiconMatch(
                        entry_id=1,
                        term="fill in",
                        category="Phrasal Verb",
                        source="auto",
                        occurrences=1,
                    )
                ]
                if has_fill_in
                else []
            )
            return AssignmentScanResultDTO(
                assignment_id=None,
                title=title,
                content_original=content_original,
                content_completed=content_completed,
                word_count=3,
                matches=matches,
                diff_chunks=[],
                duration_ms=1.0,
                message="ok",
                missing_words=[] if has_fill_in else [AssignmentMissingWord(term="fill", occurrences=1)],
                known_token_count=3 if has_fill_in else 0,
                unknown_token_count=0 if has_fill_in else 3,
                lexicon_coverage_percent=coverage,
            )

    class _StatefulSyncUseCase:
        def __init__(self, lexicon_repository: _StatefulLexiconRepository) -> None:
            self._lexicon_repository = lexicon_repository

        def execute(
            self,
            text: str,
            *,
            sync: bool | None = None,
            third_pass_enabled: bool | None = None,
            think_mode: bool | None = None,
        ) -> Result[ParseAndSyncResultDTO]:
            _ = (text, sync, third_pass_enabled, think_mode)
            self._lexicon_repository.add_phrase(value="fill in", category="Phrasal Verb")
            return Result.ok(
                ParseAndSyncResultDTO(
                    table=[],
                    summary={"sync_message": "ok"},
                    status_message="synced",
                    error_message="",
                )
            )

    lexicon_repository = _StatefulLexiconRepository()
    scanner = _CoverageScanner(lexicon_repository)
    sync_use_case = _StatefulSyncUseCase(lexicon_repository)
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=scanner,
        lexicon_repository=lexicon_repository,
        assignment_sync_use_case=sync_use_case,
        completed_threshold_percent=90.0,
    )

    result = interactor.scan_and_save(
        title="A4",
        content_original="orig",
        content_completed="Please fill in.",
    )

    assert result.success is True
    assert result.data is not None
    assert result.data.lexicon_coverage_percent == 100.0
    assert result.data.assignment_status == "COMPLETED"
    assert len(result.data.matches) == 1


def test_get_assignment_handles_invalid_not_found_and_exception() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    invalid = interactor.get_assignment(assignment_id=0)
    missing = interactor.get_assignment(assignment_id=999)

    class _BrokenRepo(_StubAssignmentRepository):
        def get_assignment(self, *, assignment_id: int) -> AssignmentRecord | None:  # type: ignore[override]
            _ = assignment_id
            raise RuntimeError("db down")

    error_result = ManageAssignmentsInteractor(
        assignment_repository=_BrokenRepo(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    ).get_assignment(assignment_id=3)

    assert invalid.success is False and invalid.status_code == "assignment_invalid_id"
    assert missing.success is False and missing.status_code == "assignment_not_found"
    assert error_result.success is False and error_result.status_code == "assignment_get_exception"


def test_update_assignment_handles_validation_not_found_and_exception() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    invalid = interactor.update_assignment(
        assignment_id=0,
        title="x",
        content_original="o",
        content_completed="c",
    )
    empty = interactor.update_assignment(
        assignment_id=3,
        title="x",
        content_original="o",
        content_completed="   ",
    )
    missing = interactor.update_assignment(
        assignment_id=777,
        title="x",
        content_original="o",
        content_completed="c",
    )

    class _BrokenRepo(_StubAssignmentRepository):
        def update_assignment_content(  # type: ignore[override]
            self,
            *,
            assignment_id: int,
            title: str,
            content_original: str,
            content_completed: str,
        ) -> AssignmentRecord | None:
            _ = (assignment_id, title, content_original, content_completed)
            raise RuntimeError("write error")

    error_result = ManageAssignmentsInteractor(
        assignment_repository=_BrokenRepo(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    ).update_assignment(
        assignment_id=3,
        title="x",
        content_original="o",
        content_completed="c",
    )

    assert invalid.status_code == "assignment_invalid_id"
    assert empty.status_code == "assignment_empty_completed_text"
    assert missing.status_code == "assignment_not_found"
    assert error_result.status_code == "assignment_update_exception"


def test_delete_and_list_handle_edge_and_exception_paths() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    assert interactor.delete_assignment(assignment_id=0).status_code == "assignment_invalid_id"
    assert interactor.delete_assignment(assignment_id=777).status_code == "assignment_not_found"

    class _BrokenRepo(_StubAssignmentRepository):
        def delete_assignment(self, *, assignment_id: int) -> bool:  # type: ignore[override]
            _ = assignment_id
            raise RuntimeError("delete fail")

        def list_assignments(self, *, limit: int = 50, offset: int = 0):  # type: ignore[override]
            _ = (limit, offset)
            raise RuntimeError("list fail")

    broken = ManageAssignmentsInteractor(
        assignment_repository=_BrokenRepo(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    assert broken.delete_assignment(assignment_id=3).status_code == "assignment_delete_exception"
    assert broken.list_assignments(limit=10, offset=0).status_code == "assignment_list_exception"


def test_suggest_quick_add_handles_empty_adjusted_and_exception_paths() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    empty = interactor.suggest_quick_add(term="   ", content_completed="x")
    adjusted = interactor.suggest_quick_add(
        term="look up",
        content_completed="Please look up values.",
        available_categories=["Verb"],
    )

    broken = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    broken._infer_quick_add_category_order = (  # type: ignore[method-assign]
        lambda term: (_ for _ in ()).throw(RuntimeError("infer boom"))
    )
    errored = broken.suggest_quick_add(term="word", content_completed="x")

    assert empty.status_code == "assignment_quick_add_suggest_empty"
    assert adjusted.success is True
    assert adjusted.data is not None
    assert adjusted.data.recommended_category == "Verb"
    assert adjusted.data.confidence <= 0.58
    assert "Adjusted to available category list." in adjusted.data.rationale
    assert errored.status_code == "assignment_quick_add_suggest_exception"


def test_bulk_delete_handles_empty_exception_and_completed_paths() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    empty = interactor.bulk_delete_assignments(assignment_ids=[])
    completed = interactor.bulk_delete_assignments(assignment_ids=[3])

    class _BrokenRepo(_StubAssignmentRepository):
        def bulk_delete_assignments(self, *, ids: list[int]) -> tuple[list[int], list[int]]:  # type: ignore[override]
            _ = ids
            raise RuntimeError("bulk delete fail")

    failed = ManageAssignmentsInteractor(
        assignment_repository=_BrokenRepo(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    ).bulk_delete_assignments(assignment_ids=[3])

    assert empty.status_code == "assignment_bulk_delete_empty"
    assert completed.success is True and completed.status_code == "assignment_bulk_delete_completed"
    assert failed.success is False and failed.status_code == "assignment_bulk_delete_failed"


def test_bulk_rescan_handles_empty_failed_and_completed_paths() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    empty = interactor.bulk_rescan_assignments(assignment_ids=[])
    completed = interactor.bulk_rescan_assignments(assignment_ids=[3])

    class _BrokenRepo(_StubAssignmentRepository):
        def get_assignment(self, *, assignment_id: int) -> AssignmentRecord | None:  # type: ignore[override]
            _ = assignment_id
            raise RuntimeError("read fail")

    failed = ManageAssignmentsInteractor(
        assignment_repository=_BrokenRepo(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    ).bulk_rescan_assignments(assignment_ids=[3])

    assert empty.status_code == "assignment_bulk_rescan_empty"
    assert completed.success is True and completed.status_code == "assignment_bulk_rescan_completed"
    assert failed.success is False and failed.status_code == "assignment_bulk_rescan_failed"


def test_quick_add_handles_empty_already_exists_and_exception_paths() -> None:
    class _IndexedLexiconRepo(_StubLexiconRepository):
        def build_index(self):  # noqa: ANN001
            return ({"details": ["Auto Added"]}, {("look", "up"): ["Phrasal Verb"]})

    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_IndexedLexiconRepo(),
    )
    empty = interactor.quick_add_missing_word(
        assignment_id=3,
        term="   ",
        content_completed="x",
        category="Auto Added",
    )
    exists = interactor.quick_add_missing_word(
        assignment_id=3,
        term="details",
        content_completed="x",
        category="Auto Added",
    )

    class _BrokenLexiconRepo(_StubLexiconRepository):
        def add_entry(self, *args, **kwargs):  # noqa: ANN002, ANN003
            _ = (args, kwargs)
            raise RuntimeError("insert fail")

    errored = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_BrokenLexiconRepo(),
    ).quick_add_missing_word(
        assignment_id=3,
        term="newword",
        content_completed="newword in sentence",
        category="Auto Added",
    )

    assert empty.status_code == "assignment_quick_add_rejected"
    assert exists.success is True and exists.status_code == "row_already_exists"
    assert errored.success is False and errored.status_code == "assignment_quick_add_exception"


def test_manage_assignments_internal_helpers_cover_branches() -> None:
    logger = _CapturingLogger()
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        completed_threshold_percent=80.0,
        logger=logger,  # type: ignore[arg-type]
    )

    assert interactor._infer_quick_add_category_order("call it a day")[0][0] == "Idiom"
    assert interactor._infer_quick_add_category_order("up")[0][0] == "Particle"
    assert interactor._infer_quick_add_category_order("quickly")[0][0] == "Adverb"
    assert interactor._infer_quick_add_category_order("worked")[0][0] == "Verb"
    assert interactor._infer_quick_add_category_order("friendship")[0][0] == "Noun"
    assert interactor._infer_quick_add_category_order("apple")[0][0] == "Auto Added"

    assert interactor._resolve_suggested_categories(suggested=["Verb"], available_categories=["Noun"]) == ["Noun"]
    assert interactor._resolve_suggested_categories(suggested=[], available_categories=None) == ["Auto Added"]
    assert interactor._normalize_assignment_ids([3, 3, -1, "x", 7]) == [3, 7]

    bulk = interactor._build_bulk_result(
        operation="bulk_rescan",
        requested_ids=[1, 2, 3, 4],
        processed_ids=[1],
        failed_ids=[2, 3, 4],
        failure_details=["#2: x", "#3: y", "#4: z", "#5: q"],
    )
    assert "..." in bulk.message
    assert interactor._resolve_assignment_status(80.0) == "COMPLETED"
    assert interactor._resolve_assignment_status(79.9) == "PENDING"
    assert interactor._extract_sentence(content="x", term="y") == ""

    class _FailingExtractor:
        def extract_sentence(self, *, text: str, term: str) -> str:
            _ = (text, term)
            raise RuntimeError("extract fail")

    interactor_with_extractor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        sentence_extractor=_FailingExtractor(),  # type: ignore[arg-type]
        logger=logger,  # type: ignore[arg-type]
    )
    assert interactor_with_extractor._extract_sentence(content="x", term="y") == ""

    class _IndexRepo(_StubLexiconRepository):
        def build_index(self):  # noqa: ANN001
            return ({"run": ["Verb"]}, {("run", "into"): ["Phrasal Verb"]})

    with_index = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_IndexRepo(),
    )
    assert with_index._exists_in_category(term="run", category="verb") is True
    assert with_index._exists_in_category(term="run into", category="phrasal verb") is True

    class _SyncOk:
        def execute(self, text: str, *, sync=None, third_pass_enabled=None, think_mode=None):  # noqa: ANN001
            _ = (text, sync, third_pass_enabled, think_mode)
            return Result.ok(
                ParseAndSyncResultDTO(table=[], summary={}, status_message="ok", error_message=""),
                status_code="ok",
            )

    class _SyncFail:
        def execute(self, text: str, *, sync=None, third_pass_enabled=None, think_mode=None):  # noqa: ANN001
            _ = (text, sync, third_pass_enabled, think_mode)
            return Result.fail("x", status_code="failed")

    class _SyncRaise:
        def execute(self, text: str, *, sync=None, third_pass_enabled=None, think_mode=None):  # noqa: ANN001
            _ = (text, sync, third_pass_enabled, think_mode)
            raise RuntimeError("sync boom")

    no_sync = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        logger=logger,  # type: ignore[arg-type]
    )
    no_sync._sync_assignment_text_to_lexicon(assignment_id=1, content_completed="", operation="x")

    ok_sync = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        assignment_sync_use_case=_SyncOk(),  # type: ignore[arg-type]
        logger=logger,  # type: ignore[arg-type]
    )
    ok_sync._sync_assignment_text_to_lexicon(assignment_id=1, content_completed="text", operation="x")

    fail_sync = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        assignment_sync_use_case=_SyncFail(),  # type: ignore[arg-type]
        logger=logger,  # type: ignore[arg-type]
    )
    fail_sync._sync_assignment_text_to_lexicon(assignment_id=1, content_completed="text", operation="x")

    raise_sync = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        assignment_sync_use_case=_SyncRaise(),  # type: ignore[arg-type]
        logger=logger,  # type: ignore[arg-type]
    )
    raise_sync._sync_assignment_text_to_lexicon(assignment_id=1, content_completed="text", operation="x")

    assert any("status=ok" in item for item in logger.info_messages)
    assert any("status=failed" in item for item in logger.info_messages)
    assert any("sync_assignment_to_lexicon" in item for item in logger.error_messages)


def test_scan_apply_status_uses_fallback_when_status_update_returns_none() -> None:
    class _StatusRepo(_StubAssignmentRepository):
        def update_assignment_status(  # type: ignore[override]
            self,
            *,
            assignment_id: int,
            status: str,
            lexicon_coverage_percent: float | None = None,
        ) -> AssignmentRecord | None:
            _ = (assignment_id, status, lexicon_coverage_percent)
            return None

    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StatusRepo(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        completed_threshold_percent=70.0,
    )
    payload = interactor._scan_and_apply_status(
        assignment_id=3,
        title="T",
        content_original="O",
        content_completed="C",
    )
    assert payload.assignment_status == "COMPLETED"


def test_scan_and_save_returns_exception_result_when_repository_fails() -> None:
    class _BrokenRepo(_StubAssignmentRepository):
        def save_assignment(  # type: ignore[override]
            self,
            *,
            title: str,
            content_original: str,
            content_completed: str,
        ) -> AssignmentRecord:
            _ = (title, content_original, content_completed)
            raise RuntimeError("save fail")

    result = ManageAssignmentsInteractor(
        assignment_repository=_BrokenRepo(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    ).scan_and_save(title="x", content_original="o", content_completed="c")
    assert result.success is False
    assert result.status_code == "assignment_scan_exception"


def test_get_assignment_returns_successful_record() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    result = interactor.get_assignment(assignment_id=3)
    assert result.success is True
    assert result.data is not None
    assert result.data.id == 3


def test_bulk_rescan_handles_scan_exception_branch() -> None:
    class _BrokenScanner:
        def scan(self, *, content_completed: str, content_original: str = "", title: str = "") -> AssignmentScanResultDTO:
            _ = (content_completed, content_original, title)
            raise RuntimeError("scan fail")

    result = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_BrokenScanner(),  # type: ignore[arg-type]
        lexicon_repository=_StubLexiconRepository(),
    ).bulk_rescan_assignments(assignment_ids=[3])
    assert result.success is False
    assert result.status_code == "assignment_bulk_rescan_failed"
    assert result.data is not None
    assert result.data.failed_ids == (3,)


def test_resolve_categories_handles_empty_duplicate_and_auto_add_fallback() -> None:
    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
    )
    resolved = interactor._resolve_suggested_categories(
        suggested=["", "Verb"],
        available_categories=["", "verb", "Verb"],
    )
    assert resolved == ["verb"]

    interactor._auto_add_category = ""
    fallback = interactor._resolve_suggested_categories(
        suggested=[""],
        available_categories=None,
    )
    assert fallback == [""]


def test_sync_assignment_skips_blank_content_when_sync_port_present() -> None:
    sync_calls: list[str] = []

    class _Sync:
        def execute(self, text: str, *, sync=None, third_pass_enabled=None, think_mode=None):  # noqa: ANN001
            _ = (sync, third_pass_enabled, think_mode)
            sync_calls.append(text)
            return Result.ok(ParseAndSyncResultDTO(table=[], summary={}, status_message="ok", error_message=""))

    interactor = ManageAssignmentsInteractor(
        assignment_repository=_StubAssignmentRepository(),
        scanner_service=_StubScanner(),
        lexicon_repository=_StubLexiconRepository(),
        assignment_sync_use_case=_Sync(),  # type: ignore[arg-type]
    )
    interactor._sync_assignment_text_to_lexicon(assignment_id=1, content_completed="   ", operation="scan")
    assert sync_calls == []
