from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LexiconStatisticsDTO:
    total_entries: int
    counts_by_status: dict[str, int]
    counts_by_source: dict[str, int]
    categories: list[tuple[str, int]]
    assignment_coverage: list[tuple[str, float, str]]
    total_assignments: int = 0
    average_assignment_coverage: float = 0.0
    low_coverage_count: int = 0
