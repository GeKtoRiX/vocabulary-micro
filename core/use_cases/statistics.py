from __future__ import annotations

from core.domain import IAssignmentRepository, ILexiconRepository, LexiconStatisticsDTO, Result


class StatisticsInteractor:
    def __init__(
        self,
        *,
        lexicon_repository: ILexiconRepository,
        assignment_repository: IAssignmentRepository,
    ) -> None:
        self._lexicon_repo = lexicon_repository
        self._assignment_repo = assignment_repository

    def execute(self) -> Result[LexiconStatisticsDTO]:
        try:
            stats = self._lexicon_repo.get_statistics()
            coverage_raw = self._assignment_repo.get_assignment_coverage_stats()
        except Exception as exc:
            return Result.fail(str(exc), status_code="statistics_error")

        total_entries = int(stats.get("total_entries", 0))
        counts_by_status: dict[str, int] = {
            str(k): int(v) for k, v in (stats.get("counts_by_status") or {}).items()
        }
        counts_by_source: dict[str, int] = {
            str(k): int(v) for k, v in (stats.get("counts_by_source") or {}).items()
        }
        categories: list[tuple[str, int]] = [
            (str(name), int(count)) for name, count in (stats.get("categories") or [])
        ]
        assignment_coverage: list[tuple[str, float, str]] = [
            (
                str(row.get("title", "")),
                float(row.get("coverage_pct", 0.0)),
                str(row.get("created_at", "")),
            )
            for row in coverage_raw
        ]
        total_assignments = len(assignment_coverage)
        average_assignment_coverage = (
            sum(item[1] for item in assignment_coverage) / total_assignments
            if total_assignments
            else 0.0
        )
        low_coverage_count = sum(1 for item in assignment_coverage if item[1] < 60.0)

        dto = LexiconStatisticsDTO(
            total_entries=total_entries,
            counts_by_status=counts_by_status,
            counts_by_source=counts_by_source,
            categories=categories,
            assignment_coverage=assignment_coverage,
            total_assignments=total_assignments,
            average_assignment_coverage=average_assignment_coverage,
            low_coverage_count=low_coverage_count,
        )
        return Result.ok(dto)
