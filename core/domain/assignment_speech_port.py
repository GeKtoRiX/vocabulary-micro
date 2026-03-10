from __future__ import annotations

from typing import Protocol

from .models import AssignmentSpeechPlayerStateDTO, AssignmentSpeechSynthesisDTO, Result


class IAssignmentSpeechPort(Protocol):
    def synthesize(
        self,
        *,
        text: str,
        title: str,
        assignment_id: int,
        voice: str,
        style_preset: str,
        output_format: str,
    ) -> Result[AssignmentSpeechSynthesisDTO]: ...

    def play(self, *, audio_path: str) -> Result[AssignmentSpeechPlayerStateDTO]: ...

    def pause(self) -> Result[AssignmentSpeechPlayerStateDTO]: ...

    def stop(self) -> Result[AssignmentSpeechPlayerStateDTO]: ...

    def status(self) -> Result[AssignmentSpeechPlayerStateDTO]: ...

    def close(self) -> None: ...
