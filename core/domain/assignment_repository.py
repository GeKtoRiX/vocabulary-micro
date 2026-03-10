from __future__ import annotations

from abc import ABC, abstractmethod

from .models import AssignmentRecord


class IAssignmentRepository(ABC):
    @abstractmethod
    def save_assignment(
        self,
        *,
        title: str,
        content_original: str,
        content_completed: str,
    ) -> AssignmentRecord:
        """Persist assignment content and return created record."""

    @abstractmethod
    def list_assignments(self, *, limit: int = 50, offset: int = 0) -> list[AssignmentRecord]:
        """List saved assignments ordered by most recent first."""

    @abstractmethod
    def get_assignment(self, *, assignment_id: int) -> AssignmentRecord | None:
        """Fetch one assignment record by id."""

    @abstractmethod
    def update_assignment_content(
        self,
        *,
        assignment_id: int,
        title: str,
        content_original: str,
        content_completed: str,
    ) -> AssignmentRecord | None:
        """Update assignment title/text payload and return persisted record when found."""

    @abstractmethod
    def delete_assignment(self, *, assignment_id: int) -> bool:
        """Delete assignment by id and return whether any row was deleted."""

    @abstractmethod
    def update_assignment_status(
        self,
        *,
        assignment_id: int,
        status: str,
        lexicon_coverage_percent: float | None = None,
    ) -> AssignmentRecord | None:
        """Update assignment status/coverage and return persisted record when found."""

    @abstractmethod
    def bulk_delete_assignments(self, *, ids: list[int]) -> tuple[list[int], list[int]]:
        """Delete multiple assignments by id list.

        Returns (deleted_ids, not_found_ids).
        """

    @abstractmethod
    def get_assignment_coverage_stats(self) -> list[dict[str, object]]:
        """Return coverage stats for all assignments: list of {title, coverage_pct, created_at}."""
