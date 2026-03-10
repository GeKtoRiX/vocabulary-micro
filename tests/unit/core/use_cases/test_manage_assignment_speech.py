from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.domain import (
    AssignmentAudioRecord,
    AssignmentRecord,
    AssignmentSpeechPlayerStateDTO,
    AssignmentSpeechSynthesisDTO,
    Result,
)
from core.use_cases.manage_assignment_speech import ManageAssignmentSpeechInteractor


class _StubAssignmentRepository:
    def __init__(self) -> None:
        self._records: dict[int, AssignmentRecord] = {
            1: AssignmentRecord(
                id=1,
                title="A1",
                content_original="Original",
                content_completed="Completed text",
                status="PENDING",
                lexicon_coverage_percent=0.0,
            ),
            2: AssignmentRecord(
                id=2,
                title="A2",
                content_original="Original",
                content_completed="   ",
                status="PENDING",
                lexicon_coverage_percent=0.0,
            ),
        }

    def get_assignment(self, *, assignment_id: int) -> AssignmentRecord | None:
        return self._records.get(int(assignment_id))


class _StubAudioRepository:
    def __init__(self) -> None:
        self.records: list[AssignmentAudioRecord] = []
        self.deleted_assignment_ids: list[int] = []
        self.list_calls: list[tuple[int, int, int]] = []

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
        record = AssignmentAudioRecord(
            id=len(self.records) + 1,
            assignment_id=int(assignment_id),
            audio_path=str(audio_path),
            audio_format=str(audio_format),
            voice=str(voice),
            style_preset=str(style_preset),
            duration_sec=float(duration_sec),
            sample_rate=int(sample_rate),
            created_at="2026-03-03T00:00:00+00:00",
        )
        self.records.append(record)
        return record

    def get_latest_audio_record(self, *, assignment_id: int) -> AssignmentAudioRecord | None:
        filtered = [item for item in self.records if int(item.assignment_id) == int(assignment_id)]
        if not filtered:
            return None
        return filtered[-1]

    def list_audio_records(
        self,
        *,
        assignment_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AssignmentAudioRecord]:
        self.list_calls.append((int(assignment_id), int(limit), int(offset)))
        filtered = [item for item in self.records if int(item.assignment_id) == int(assignment_id)]
        safe_offset = max(0, int(offset))
        safe_limit = max(1, int(limit))
        return filtered[safe_offset : safe_offset + safe_limit]

    def delete_audio_records_for_assignment(self, *, assignment_id: int) -> int:
        safe_id = int(assignment_id)
        before = len(self.records)
        self.records = [item for item in self.records if int(item.assignment_id) != safe_id]
        deleted = before - len(self.records)
        self.deleted_assignment_ids.append(safe_id)
        return deleted


class _StubSpeechPort:
    def __init__(self) -> None:
        self.synthesize_calls: list[dict[str, object]] = []
        self.play_calls: list[str] = []
        self.pause_calls = 0
        self.stop_calls = 0
        self.status_calls = 0
        self.synthesize_result: Result[AssignmentSpeechSynthesisDTO] = Result.ok(
            AssignmentSpeechSynthesisDTO(
                audio_path="audio/a1.wav",
                audio_format="wav",
                voice="af_heart",
                style_preset="neutral",
                duration_sec=3.2,
                sample_rate=24000,
            )
        )
        self.play_result: Result[AssignmentSpeechPlayerStateDTO] = Result.ok(
            AssignmentSpeechPlayerStateDTO(
                state="playing",
                position_sec=0.0,
                duration_sec=3.2,
                audio_path="audio/a1.wav",
                message="",
            )
        )

    def synthesize(
        self,
        *,
        text: str,
        title: str,
        assignment_id: int,
        voice: str,
        style_preset: str,
        output_format: str,
    ) -> Result[AssignmentSpeechSynthesisDTO]:
        self.synthesize_calls.append(
            {
                "text": text,
                "title": title,
                "assignment_id": assignment_id,
                "voice": voice,
                "style_preset": style_preset,
                "output_format": output_format,
            }
        )
        return self.synthesize_result

    def play(self, *, audio_path: str) -> Result[AssignmentSpeechPlayerStateDTO]:
        self.play_calls.append(str(audio_path))
        return self.play_result

    def pause(self) -> Result[AssignmentSpeechPlayerStateDTO]:
        self.pause_calls += 1
        return Result.ok(AssignmentSpeechPlayerStateDTO(state="paused"))

    def stop(self) -> Result[AssignmentSpeechPlayerStateDTO]:
        self.stop_calls += 1
        return Result.ok(AssignmentSpeechPlayerStateDTO(state="stopped"))

    def status(self) -> Result[AssignmentSpeechPlayerStateDTO]:
        self.status_calls += 1
        return Result.ok(AssignmentSpeechPlayerStateDTO(state="idle"))

    def close(self) -> None:
        return


def _build_interactor(
    *,
    default_voice: str = "Vivian",
    default_style_preset: str = "Speak naturally and clearly.",
    default_output_format: str = "wav",
    default_autoplay: bool = True,
    runtime_defaults_provider: Callable[[], object] | None = None,
) -> tuple[
    ManageAssignmentSpeechInteractor,
    _StubAssignmentRepository,
    _StubAudioRepository,
    _StubSpeechPort,
]:
    assignment_repository = _StubAssignmentRepository()
    audio_repository = _StubAudioRepository()
    speech_port = _StubSpeechPort()
    interactor = ManageAssignmentSpeechInteractor(
        assignment_repository=assignment_repository,
        audio_repository=audio_repository,
        speech_port=speech_port,
        default_voice=default_voice,
        default_style_preset=default_style_preset,
        default_output_format=default_output_format,
        default_autoplay=default_autoplay,
        runtime_defaults_provider=runtime_defaults_provider,
        logger=None,
    )
    return interactor, assignment_repository, audio_repository, speech_port


def test_generate_for_assignment_success_persists_metadata_and_autoplays() -> None:
    interactor, _, audio_repository, speech_port = _build_interactor(default_autoplay=True)

    result = interactor.generate_for_assignment(assignment_id=1)

    assert result.success is True
    assert result.data is not None
    assert result.data.audio_record is not None
    assert result.data.audio_record.audio_path == "audio/a1.wav"
    assert len(audio_repository.records) == 1
    assert speech_port.play_calls == ["audio/a1.wav"]
    assert result.data.player_state.state == "playing"


def test_generate_for_assignment_fails_when_assignment_not_found() -> None:
    interactor, _, _, _ = _build_interactor()

    result = interactor.generate_for_assignment(assignment_id=999)

    assert result.success is False
    assert result.status_code == "assignment_speech_assignment_not_found"


def test_generate_for_assignment_fails_when_completed_text_empty() -> None:
    interactor, _, _, _ = _build_interactor()

    result = interactor.generate_for_assignment(assignment_id=2)

    assert result.success is False
    assert result.status_code == "assignment_speech_empty_completed_text"


def test_generate_for_assignment_fails_when_sidecar_returns_error() -> None:
    interactor, _, audio_repository, speech_port = _build_interactor()
    speech_port.synthesize_result = Result.fail(
        "Synthesis failed.",
        status_code="sidecar_synthesize_failed",
    )

    result = interactor.generate_for_assignment(assignment_id=1)

    assert result.success is False
    assert result.status_code == "sidecar_synthesize_failed"
    assert not audio_repository.records


def test_generate_for_assignment_respects_default_autoplay_setting() -> None:
    interactor, _, _, speech_port = _build_interactor(default_autoplay=False)

    result = interactor.generate_for_assignment(assignment_id=1)

    assert result.success is True
    assert result.data is not None
    assert result.data.player_state.state == "idle"
    assert speech_port.play_calls == []
    assert "Use Play to start" in result.data.message


def test_generate_for_assignment_reuses_existing_audio_without_synthesis(tmp_path: Path) -> None:
    interactor, _, audio_repository, speech_port = _build_interactor(default_autoplay=True)
    ready_audio = tmp_path / "ready.wav"
    ready_audio.write_bytes(b"RIFF")
    audio_repository.records.append(
        AssignmentAudioRecord(
            id=1,
            assignment_id=1,
            audio_path=str(ready_audio),
            audio_format="wav",
            voice="af_heart",
            style_preset="neutral",
            duration_sec=1.2,
            sample_rate=24_000,
            created_at="2026-03-03T00:00:00+00:00",
        )
    )

    result = interactor.generate_for_assignment(assignment_id=1)

    assert result.success is True
    assert result.status_code == "assignment_speech_reused_existing_audio"
    assert speech_port.synthesize_calls == []
    assert speech_port.play_calls == [str(ready_audio)]


def test_generate_for_assignment_force_regenerate_ignores_existing_audio(tmp_path: Path) -> None:
    interactor, _, audio_repository, speech_port = _build_interactor(default_autoplay=False)
    ready_audio = tmp_path / "ready.wav"
    ready_audio.write_bytes(b"RIFF")
    audio_repository.records.append(
        AssignmentAudioRecord(
            id=1,
            assignment_id=1,
            audio_path=str(ready_audio),
            audio_format="wav",
            voice="Vivian",
            style_preset="Speak naturally and clearly.",
            duration_sec=1.2,
            sample_rate=24_000,
            created_at="2026-03-03T00:00:00+00:00",
        )
    )
    speech_port.synthesize_result = Result.ok(
        AssignmentSpeechSynthesisDTO(
            audio_path="audio/forced.wav",
            audio_format="wav",
            voice="Vivian",
            style_preset="Speak naturally and clearly.",
            duration_sec=2.5,
            sample_rate=24_000,
        )
    )

    result = interactor.generate_for_assignment(
        assignment_id=1,
        force_regenerate=True,
    )

    assert result.success is True
    assert result.status_code == "assignment_speech_generated"
    assert len(speech_port.synthesize_calls) == 1
    assert speech_port.play_calls == []
    assert not ready_audio.exists()
    assert len(audio_repository.records) == 1
    assert audio_repository.records[0].audio_path == "audio/forced.wav"


def test_generate_for_assignment_empty_defaults_fallback_to_builtin_defaults() -> None:
    interactor, _, _, speech_port = _build_interactor(
        default_voice="",
        default_style_preset="",
    )

    result = interactor.generate_for_assignment(
        assignment_id=1,
        autoplay=False,
        force_regenerate=True,
    )

    assert result.success is True
    assert speech_port.synthesize_calls
    synth_call = speech_port.synthesize_calls[0]
    assert synth_call["voice"] == "Vivian"
    assert synth_call["style_preset"] == "Speak naturally and clearly."


def test_generate_for_assignment_refreshes_runtime_defaults_from_provider() -> None:
    provider_payload = {
        "default_voice": "Serena",
        "default_style_preset": "Speak clearly and naturally at a measured pace.",
        "default_output_format": "mp3",
        "autoplay_on_generate": False,
    }
    interactor, _, _, speech_port = _build_interactor(
        default_voice="Vivian",
        default_style_preset="Speak naturally and clearly.",
        default_output_format="wav",
        default_autoplay=True,
        runtime_defaults_provider=lambda: provider_payload,
    )

    result = interactor.generate_for_assignment(
        assignment_id=1,
        force_regenerate=True,
    )

    assert result.success is True
    assert speech_port.synthesize_calls
    synth_call = speech_port.synthesize_calls[0]
    assert synth_call["voice"] == "Serena"
    assert synth_call["style_preset"] == "Speak clearly and naturally at a measured pace."
    assert synth_call["output_format"] == "mp3"
    assert speech_port.play_calls == []
