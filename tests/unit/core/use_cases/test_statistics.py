from __future__ import annotations

from core.use_cases.statistics import StatisticsInteractor


class _LexiconRepoOk:
    def get_statistics(self) -> dict[str, object]:
        return {
            "total_entries": "5",
            "counts_by_status": {"approved": "3", "pending_review": 2},
            "counts_by_source": {"manual": "4", "auto": 1},
            "categories": [("Verb", "2"), ("Noun", 3)],
        }


class _AssignmentRepoOk:
    def get_assignment_coverage_stats(self) -> list[dict[str, object]]:
        return [
            {"title": "A1", "coverage_pct": "92.5", "created_at": "2026-03-03T10:00:00"},
            {"title": "A2", "coverage_pct": 50, "created_at": "2026-03-03T11:00:00"},
        ]


class _LexiconRepoDefaults:
    def get_statistics(self) -> dict[str, object]:
        return {}


class _AssignmentRepoDefaults:
    def get_assignment_coverage_stats(self) -> list[dict[str, object]]:
        return [{}]


class _LexiconRepoError:
    def get_statistics(self) -> dict[str, object]:
        raise RuntimeError("stats db error")


def test_statistics_interactor_builds_typed_dto() -> None:
    interactor = StatisticsInteractor(
        lexicon_repository=_LexiconRepoOk(),  # type: ignore[arg-type]
        assignment_repository=_AssignmentRepoOk(),  # type: ignore[arg-type]
    )

    result = interactor.execute()

    assert result.success is True
    assert result.error_message is None
    assert result.data is not None
    assert result.data.total_entries == 5
    assert result.data.counts_by_status == {"approved": 3, "pending_review": 2}
    assert result.data.counts_by_source == {"manual": 4, "auto": 1}
    assert result.data.categories == [("Verb", 2), ("Noun", 3)]
    assert result.data.assignment_coverage == [
        ("A1", 92.5, "2026-03-03T10:00:00"),
        ("A2", 50.0, "2026-03-03T11:00:00"),
    ]
    assert result.data.total_assignments == 2
    assert result.data.average_assignment_coverage == 71.25
    assert result.data.low_coverage_count == 1


def test_statistics_interactor_uses_safe_defaults() -> None:
    interactor = StatisticsInteractor(
        lexicon_repository=_LexiconRepoDefaults(),  # type: ignore[arg-type]
        assignment_repository=_AssignmentRepoDefaults(),  # type: ignore[arg-type]
    )

    result = interactor.execute()

    assert result.success is True
    assert result.data is not None
    assert result.data.total_entries == 0
    assert result.data.counts_by_status == {}
    assert result.data.counts_by_source == {}
    assert result.data.categories == []
    assert result.data.assignment_coverage == [("", 0.0, "")]
    assert result.data.total_assignments == 1
    assert result.data.average_assignment_coverage == 0.0
    assert result.data.low_coverage_count == 1


def test_statistics_interactor_returns_error_result_on_exception() -> None:
    interactor = StatisticsInteractor(
        lexicon_repository=_LexiconRepoError(),  # type: ignore[arg-type]
        assignment_repository=_AssignmentRepoOk(),  # type: ignore[arg-type]
    )

    result = interactor.execute()
    assert result.success is False
    assert result.status_code == "statistics_error"
    assert result.error_message == "stats db error"
