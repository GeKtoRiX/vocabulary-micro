from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from core.domain import (
    AssignmentAudioRecord,
    AssignmentSpeechPlayerStateDTO,
    AssignmentSpeechResultDTO,
    AssignmentSpeechSynthesisDTO,
    IAssignmentAudioRepository,
    IAssignmentRepository,
    IAssignmentSpeechPort,
    ILoggingService,
    Result,
)
from core.use_cases._base import BaseInteractor


class ManageAssignmentSpeechInteractor(BaseInteractor):
    def __init__(
        self,
        *,
        assignment_repository: IAssignmentRepository,
        audio_repository: IAssignmentAudioRepository,
        speech_port: IAssignmentSpeechPort,
        default_voice: str = "Vivian",
        default_style_preset: str = "Speak naturally and clearly.",
        default_output_format: str = "wav",
        default_autoplay: bool = True,
        runtime_defaults_provider: Callable[[], object] | None = None,
        logger: ILoggingService | None = None,
    ) -> None:
        self._assignment_repository = assignment_repository
        self._audio_repository = audio_repository
        self._speech_port = speech_port
        self._default_voice = str(default_voice or "").strip() or "Vivian"
        self._default_style_preset = (
            str(default_style_preset or "").strip() or "Speak naturally and clearly."
        )
        self._default_output_format = str(default_output_format or "").strip().lower() or "wav"
        self._default_autoplay = bool(default_autoplay)
        self._runtime_defaults_provider = runtime_defaults_provider
        self._logger = logger

    def generate_for_assignment(
        self,
        *,
        assignment_id: int,
        autoplay: bool | None = None,
        force_regenerate: bool = False,
    ) -> Result[AssignmentSpeechResultDTO]:
        self._refresh_runtime_defaults()
        autoplay_enabled = self._default_autoplay if autoplay is None else bool(autoplay)
        safe_id = int(assignment_id)
        if safe_id <= 0:
            return Result.fail(
                "Invalid assignment id.",
                status_code="assignment_speech_invalid_id",
            )
        try:
            assignment = self._assignment_repository.get_assignment(assignment_id=safe_id)
        except Exception as exc:
            self._log_error(operation="assignment_speech_get_assignment", error=exc)
            return Result.fail(
                f"Assignment speech failed: {exc}",
                status_code="assignment_speech_get_assignment_exception",
            )
        if assignment is None:
            return Result.fail(
                f"Assignment #{safe_id} not found.",
                status_code="assignment_speech_assignment_not_found",
            )
        completed_text = str(assignment.content_completed or "")
        if not completed_text.strip():
            return Result.fail(
                "Completed assignment text is empty.",
                status_code="assignment_speech_empty_completed_text",
            )
        existing_audio = None
        if not bool(force_regenerate):
            existing_audio = self._load_reusable_audio_record(assignment_id=safe_id)
        if existing_audio is not None:
            player_state = AssignmentSpeechPlayerStateDTO(
                state="idle",
                position_sec=0.0,
                duration_sec=float(existing_audio.duration_sec),
                audio_path=str(existing_audio.audio_path),
                message="",
            )
            if autoplay_enabled:
                play_result = self._normalize_player_state_result(
                    self._speech_port.play(audio_path=str(existing_audio.audio_path)),
                    fallback_message="Autoplay failed.",
                )
                if play_result.success and play_result.data is not None:
                    player_state = play_result.data
                elif play_result.error_message:
                    player_state = AssignmentSpeechPlayerStateDTO(
                        state="error",
                        position_sec=0.0,
                        duration_sec=float(existing_audio.duration_sec),
                        audio_path=str(existing_audio.audio_path),
                        message=str(play_result.error_message),
                    )
            message = (
                f"Speech ready for assignment #{safe_id} from existing audio."
                if autoplay_enabled
                else f"Speech ready for assignment #{safe_id}. Use Play to start."
            )
            payload_dto = AssignmentSpeechResultDTO(
                assignment_id=safe_id,
                audio_record=existing_audio,
                player_state=player_state,
                message=message,
            )
            self._log_info(
                "assignment_speech_reuse_existing: "
                f"id={safe_id}, path={existing_audio.audio_path}, autoplay={'yes' if autoplay_enabled else 'no'}"
            )
            return Result.ok(
                payload_dto,
                status_code="assignment_speech_reused_existing_audio",
            )
        # Stop any active playback and remove existing audio files before regenerating.
        try:
            self._speech_port.stop()
        except Exception:
            pass
        try:
            existing_records = self._audio_repository.list_audio_records(
                assignment_id=safe_id, limit=200, offset=0
            )
        except Exception as exc:
            self._log_error(operation="assignment_speech_list_existing_audio", error=exc)
            existing_records = []
        for record in existing_records:
            try:
                path = Path(str(record.audio_path or "")).expanduser().resolve()
                if path.exists():
                    os.remove(path)
            except Exception:
                pass
        try:
            self._audio_repository.delete_audio_records_for_assignment(assignment_id=safe_id)
        except Exception as exc:
            self._log_error(operation="assignment_speech_delete_audio_records", error=exc)

        synthesize_result = self._speech_port.synthesize(
            text=completed_text,
            title=str(assignment.title or ""),
            assignment_id=safe_id,
            voice=self._default_voice,
            style_preset=self._default_style_preset,
            output_format=self._default_output_format,
        )
        payload = (
            synthesize_result.data
            if isinstance(synthesize_result.data, AssignmentSpeechSynthesisDTO)
            else None
        )
        if payload is None:
            return Result.fail(
                str(synthesize_result.error_message or "Speech synthesis failed."),
                status_code=synthesize_result.status_code or "assignment_speech_synthesize_failed",
            )
        audio_path = str(payload.audio_path or "").strip()
        if not audio_path:
            return Result.fail(
                "Speech synthesis failed: output file path is missing.",
                status_code="assignment_speech_synthesize_missing_audio_path",
            )

        try:
            persisted_record = self._audio_repository.save_audio_record(
                assignment_id=safe_id,
                audio_path=audio_path,
                audio_format=str(payload.audio_format or "").strip().lower() or self._default_output_format,
                voice=str(payload.voice or "").strip() or self._default_voice,
                style_preset=str(payload.style_preset or "").strip() or self._default_style_preset,
                duration_sec=self._as_float(payload.duration_sec, default=0.0),
                sample_rate=self._as_int(payload.sample_rate, default=0),
            )
        except Exception as exc:
            self._log_error(operation="assignment_speech_save_audio_record", error=exc)
            return Result.fail(
                f"Speech metadata save failed: {exc}",
                status_code="assignment_speech_save_audio_record_exception",
            )

        player_state = AssignmentSpeechPlayerStateDTO(
            state="idle",
            position_sec=0.0,
            duration_sec=float(persisted_record.duration_sec),
            audio_path=str(persisted_record.audio_path),
            message="",
        )
        if autoplay_enabled:
            play_result = self._normalize_player_state_result(
                self._speech_port.play(audio_path=str(persisted_record.audio_path)),
                fallback_message="Autoplay failed.",
            )
            if play_result.success and play_result.data is not None:
                player_state = play_result.data
            elif play_result.error_message:
                player_state = AssignmentSpeechPlayerStateDTO(
                    state="error",
                    position_sec=0.0,
                    duration_sec=float(persisted_record.duration_sec),
                    audio_path=str(persisted_record.audio_path),
                    message=str(play_result.error_message),
                )

        message = (
            f"Speech generated for assignment #{safe_id}."
            if autoplay_enabled
            else f"Speech generated for assignment #{safe_id}. Use Play to start."
        )
        self._log_info(
            "assignment_speech_generate: "
            f"id={safe_id}, path={persisted_record.audio_path}, format={persisted_record.audio_format}, "
            f"voice={persisted_record.voice}, style={persisted_record.style_preset}, "
            f"duration_sec={persisted_record.duration_sec:.3f}, autoplay={'yes' if autoplay_enabled else 'no'}"
        )
        payload_dto = AssignmentSpeechResultDTO(
            assignment_id=safe_id,
            audio_record=persisted_record,
            player_state=player_state,
            message=message,
        )
        return Result.ok(payload_dto, status_code="assignment_speech_generated")

    def play_latest_for_assignment(
        self,
        *,
        assignment_id: int,
    ) -> Result[AssignmentSpeechPlayerStateDTO]:
        safe_id = int(assignment_id)
        if safe_id <= 0:
            return Result.fail(
                "Invalid assignment id.",
                status_code="assignment_speech_invalid_id",
            )
        try:
            latest = self._audio_repository.get_latest_audio_record(assignment_id=safe_id)
        except Exception as exc:
            self._log_error(operation="assignment_speech_get_latest_audio", error=exc)
            return Result.fail(
                f"Speech playback failed: {exc}",
                status_code="assignment_speech_get_latest_audio_exception",
            )
        if latest is None:
            return Result.fail(
                "No generated audio found for this assignment.",
                status_code="assignment_speech_audio_not_found",
            )
        return self._normalize_player_state_result(
            self._speech_port.play(audio_path=str(latest.audio_path)),
            fallback_message="Playback failed.",
        )

    def pause_playback(self) -> Result[AssignmentSpeechPlayerStateDTO]:
        return self._normalize_player_state_result(
            self._speech_port.pause(),
            fallback_message="Pause failed.",
        )

    def stop_playback(self) -> Result[AssignmentSpeechPlayerStateDTO]:
        return self._normalize_player_state_result(
            self._speech_port.stop(),
            fallback_message="Stop failed.",
        )

    def get_player_state(self) -> Result[AssignmentSpeechPlayerStateDTO]:
        return self._normalize_player_state_result(
            self._speech_port.status(),
            fallback_message="Player status unavailable.",
        )

    def close(self) -> None:
        try:
            self._speech_port.close()
        except Exception as exc:
            self._log_error(operation="assignment_speech_close", error=exc)

    def _normalize_player_state_result(
        self,
        result: Result[AssignmentSpeechPlayerStateDTO],
        *,
        fallback_message: str,
    ) -> Result[AssignmentSpeechPlayerStateDTO]:
        if isinstance(result.data, AssignmentSpeechPlayerStateDTO):
            return result
        if isinstance(result.data, dict):
            state = self._to_player_state(result.data)
            if result.success:
                return Result.ok(state, status_code=result.status_code)
            return Result.fail(
                result.error_message or state.message or fallback_message,
                status_code=result.status_code,
                data=state,
            )
        if result.success:
            state = AssignmentSpeechPlayerStateDTO(
                state="idle",
                position_sec=0.0,
                duration_sec=0.0,
                audio_path="",
                message="",
            )
            return Result.ok(state, status_code=result.status_code)
        return Result.fail(
            result.error_message or fallback_message,
            status_code=result.status_code,
            data=AssignmentSpeechPlayerStateDTO(
                state="error",
                position_sec=0.0,
                duration_sec=0.0,
                audio_path="",
                message=str(result.error_message or fallback_message),
            ),
        )

    def _to_player_state(
        self,
        payload: dict[str, object],
    ) -> AssignmentSpeechPlayerStateDTO:
        return AssignmentSpeechPlayerStateDTO(
            state=str(payload.get("state", "") or "").strip().lower() or "idle",
            position_sec=self._as_float(payload.get("position_sec"), default=0.0),
            duration_sec=self._as_float(payload.get("duration_sec"), default=0.0),
            audio_path=str(payload.get("audio_path", "") or "").strip(),
            message=str(payload.get("message", "") or "").strip(),
        )

    def _as_float(self, value: object, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _as_int(self, value: object, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _refresh_runtime_defaults(self) -> None:
        provider = self._runtime_defaults_provider
        if provider is None:
            return
        try:
            payload = provider()
        except Exception as exc:
            self._log_error(
                operation="assignment_speech_runtime_defaults_provider",
                error=exc,
            )
            return
        voice = self._as_non_empty_str(self._resolve_provider_value(payload, "default_voice"))
        if voice:
            self._default_voice = voice
        style = self._as_non_empty_str(self._resolve_provider_value(payload, "default_style_preset"))
        if style:
            self._default_style_preset = style
        output_format = self._as_non_empty_str(
            self._resolve_provider_value(payload, "default_output_format")
        ).lower()
        if output_format:
            self._default_output_format = output_format
        autoplay = self._resolve_provider_value(payload, "autoplay_on_generate")
        if isinstance(autoplay, bool):
            self._default_autoplay = autoplay

    @staticmethod
    def _resolve_provider_value(payload: object, key: str) -> object | None:
        if isinstance(payload, dict):
            return payload.get(key)
        return getattr(payload, key, None)

    @staticmethod
    def _as_non_empty_str(value: object) -> str:
        candidate = str(value or "").strip()
        return candidate

    def _load_reusable_audio_record(self, *, assignment_id: int) -> AssignmentAudioRecord | None:
        try:
            latest = self._audio_repository.get_latest_audio_record(assignment_id=assignment_id)
        except Exception as exc:
            self._log_error(operation="assignment_speech_get_latest_audio_record", error=exc)
            return None
        if latest is None:
            return None
        path = Path(str(latest.audio_path or "")).expanduser().resolve()
        if not path.exists():
            return None
        return latest
