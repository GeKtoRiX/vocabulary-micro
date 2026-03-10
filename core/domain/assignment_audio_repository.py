from __future__ import annotations

from abc import ABC, abstractmethod

from .models import AssignmentAudioRecord


class IAssignmentAudioRepository(ABC):
    @abstractmethod
    def save_audio_record(
        self,
        *,
        assignment_id: int,
        audio_path: str,
        audio_format: str,
        voice: str,
        style_preset: str,
        duration_sec: float = 0.0,
        sample_rate: int = 0,
    ) -> AssignmentAudioRecord:
        """Persist generated assignment audio metadata."""

    @abstractmethod
    def get_latest_audio_record(self, *, assignment_id: int) -> AssignmentAudioRecord | None:
        """Fetch latest generated audio metadata for one assignment."""

    @abstractmethod
    def list_audio_records(
        self,
        *,
        assignment_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AssignmentAudioRecord]:
        """List audio metadata rows for one assignment ordered by latest first."""

    @abstractmethod
    def delete_audio_records_for_assignment(self, *, assignment_id: int) -> int:
        """Delete all audio DB records for an assignment. Returns count deleted."""
