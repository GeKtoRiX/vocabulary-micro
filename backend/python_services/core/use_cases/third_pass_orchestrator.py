from __future__ import annotations

import time
from typing import Any, Callable

from backend.python_services.core.domain import ILexiconRepository, ParseSyncSettings
import backend.python_services.core.domain.reason_codes as domain_reasons
from backend.python_services.core.domain.services import TextProcessor


THIRD_PASS_SCHEMA_VERSION = 1

_ErrorLogger = Callable[[str, Exception], None]


class ThirdPassOrchestrator:
    """Owns third-pass validation policy and LLM integration details."""

    def __init__(
        self,
        *,
        repository: ILexiconRepository,
        settings: ParseSyncSettings,
        text_processor: TextProcessor,
        auto_add_category: str,
        log_error: _ErrorLogger | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._text_processor = text_processor
        self._auto_add_category = str(auto_add_category or "").strip() or "Auto Added"
        self._log_error_callback = log_error

    def default_summary(self, *, enabled: bool, reason: str) -> dict[str, Any]:
        return {
            "schema_version": THIRD_PASS_SCHEMA_VERSION,
            "enabled": enabled,
            "status": "skipped",
            "reason": reason,
            "model_info": {},
            "candidates_count": 0,
            "resolved_count": 0,
            "uncertain_count": 0,
            "occurrences": [],
            "stage_statuses": [],
            "cache_hit": False,
            "sync_enabled": False,
            "sync_stage_status": {
                "status": "skipped",
                "reason": domain_reasons.REASON_THIRD_PASS_NOT_SYNCED,
                "duration_ms": 0.0,
            },
            "added": [],
            "already_existed": [],
            "queued_for_sync": [],
            "rejected_candidates": [],
            "category_review_required": [],
        }

    def evaluate_validation_policy(
        self,
        *,
        third_pass_requested: bool,
        second_pass_requested: bool,
        second_pass_summary: dict[str, Any],
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "allowed": False,
            "reason": domain_reasons.REASON_NOT_REQUESTED,
            "max_trf_confidence": 0.0,
            "suspicious_trf_uncertain_count": 0,
        }
        if not third_pass_requested:
            return payload
        if not second_pass_requested:
            payload["reason"] = domain_reasons.REASON_VALIDATION_REQUIRES_SECOND_PASS
            return payload

        occurrences = second_pass_summary.get("occurrences")
        if not isinstance(occurrences, list) or not occurrences:
            payload["allowed"] = True
            payload["reason"] = domain_reasons.REASON_VALIDATION_SECOND_PASS_EMPTY_FALLBACK
            return payload

        max_trf_confidence = 0.0
        suspicious_count = 0
        trf_signal_count = 0
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                continue
            source = str(occurrence.get("source", "")).strip().lower()
            if source != domain_reasons.TRF_SEMANTIC_SOURCE:
                continue
            trf_signal_count += 1
            confidence = self._safe_float(occurrence.get("score"), default=0.0)
            if confidence > max_trf_confidence:
                max_trf_confidence = confidence
            status = str(occurrence.get("status", "")).strip().lower()
            if status in {"", "uncertain", "failed", "partial"}:
                suspicious_count += 1

        payload["max_trf_confidence"] = round(max_trf_confidence, 4)
        payload["suspicious_trf_uncertain_count"] = suspicious_count
        payload["trf_signal_count"] = trf_signal_count

        if max_trf_confidence > float(self._settings.trf_confidence_threshold):
            payload["reason"] = domain_reasons.REASON_VALIDATION_BLOCKED_HIGH_CONFIDENCE_TRF
            return payload
        if suspicious_count > 0:
            payload["allowed"] = True
            payload["reason"] = domain_reasons.REASON_VALIDATION_SUSPICIOUS_TRF_UNCERTAIN
            return payload
        if trf_signal_count > 0:
            payload["reason"] = domain_reasons.REASON_VALIDATION_TRF_NOT_UNCERTAIN
            return payload

        payload["allowed"] = True
        payload["reason"] = domain_reasons.REASON_VALIDATION_NO_TRF_SIGNAL_FALLBACK
        return payload

    def run(
        self,
        *,
        text: str,
        request_id: str,
        think_mode: bool | None,
        enabled: bool,
        timeout_ms: int | None,
    ) -> dict[str, Any]:
        try:
            payload = self._call_third_pass_extractor(
                text=text,
                request_id=request_id,
                think_mode=think_mode,
                enabled=enabled,
                timeout_ms=timeout_ms,
            )
        except Exception as exc:
            self._log_error("run_third_pass", exc)
            return {
                **self.default_summary(
                    enabled=True,
                    reason=domain_reasons.REASON_THIRD_PASS_FAILED,
                ),
                "status": "failed",
                "reason": domain_reasons.REASON_THIRD_PASS_FAILED,
                "error": str(exc),
            }

        if not isinstance(payload, dict):
            return {
                **self.default_summary(
                    enabled=True,
                    reason=domain_reasons.REASON_INVALID_THIRD_PASS_PAYLOAD,
                ),
                "status": "failed",
                "reason": domain_reasons.REASON_INVALID_THIRD_PASS_PAYLOAD,
            }

        normalized = dict(payload)
        normalized.setdefault("schema_version", THIRD_PASS_SCHEMA_VERSION)
        normalized.setdefault("enabled", True)
        normalized.setdefault("status", "ok")
        normalized.setdefault("reason", domain_reasons.REASON_NONE)
        normalized.setdefault("model_info", {})
        normalized.setdefault("candidates_count", 0)
        normalized.setdefault("resolved_count", 0)
        normalized.setdefault("uncertain_count", 0)
        normalized.setdefault("occurrences", [])
        normalized.setdefault("stage_statuses", [])
        normalized.setdefault("cache_hit", False)
        normalized.setdefault("sync_enabled", False)
        normalized.setdefault(
            "sync_stage_status",
            {
                "status": "skipped",
                "reason": domain_reasons.REASON_THIRD_PASS_NOT_SYNCED,
                "duration_ms": 0.0,
            },
        )
        normalized.setdefault("added", [])
        normalized.setdefault("already_existed", [])
        normalized.setdefault("queued_for_sync", [])
        normalized.setdefault("rejected_candidates", [])
        normalized.setdefault("category_review_required", [])
        return normalized

    def extract_second_pass_sync_candidates(
        self,
        second_pass_summary: dict[str, Any],
    ) -> tuple[list[str], dict[str, str]]:
        return self.extract_occurrence_sync_candidates(second_pass_summary)

    def extract_occurrence_sync_candidates(
        self,
        summary_payload: dict[str, Any],
    ) -> tuple[list[str], dict[str, str]]:
        return self._text_processor.extract_occurrence_sync_candidates(
            summary_payload.get("occurrences"),
            auto_add_category=self._auto_add_category,
        )

    def call_third_pass_extractor(
        self,
        *,
        text: str,
        request_id: str,
        think_mode: bool | None,
        enabled: bool,
        timeout_ms: int | None,
    ) -> Any:
        return self._call_third_pass_extractor(
            text=text,
            request_id=request_id,
            think_mode=think_mode,
            enabled=enabled,
            timeout_ms=timeout_ms,
        )

    def resolve_mwe_repository_target(self) -> Any | None:
        return self._resolve_mwe_repository_target()

    def guess_phrasal_parts(self, candidate: str, expression_type: str) -> tuple[str, str]:
        return self._guess_phrasal_parts(candidate, expression_type)

    def upsert_mwe_records_from_occurrences(
        self,
        occurrences: Any,
        *,
        request_id: str,
    ) -> dict[str, object]:
        if not isinstance(occurrences, list):
            return {
                "status": "skipped",
                "reason": domain_reasons.REASON_INVALID_OCCURRENCES,
                "duration_ms": 0.0,
                "upserted_count": 0,
                "failed_count": 0,
            }

        target = self._resolve_mwe_repository_target()
        if target is None:
            return {
                "status": "skipped",
                "reason": domain_reasons.REASON_MWE_REPOSITORY_UNAVAILABLE,
                "duration_ms": 0.0,
                "upserted_count": 0,
                "failed_count": 0,
            }

        stage_start = time.perf_counter()
        upserted = 0
        failed = 0
        seen: set[tuple[str, str]] = set()

        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                continue
            expression_type = str(occurrence.get("expression_type", "")).strip().lower()
            if expression_type not in {"phrasal_verb", "idiom"}:
                continue

            candidate = str(
                occurrence.get("canonical_form")
                or occurrence.get("surface")
                or ""
            ).strip().lower()
            candidate = self._text_processor.canonicalize_expression(
                candidate,
                expression_type=expression_type,
            )
            if not candidate:
                continue

            marker = (candidate, expression_type)
            if marker in seen:
                continue
            seen.add(marker)

            base_lemma, particle = self._guess_phrasal_parts(candidate, expression_type)
            sense_key = f"llm_{candidate.replace(' ', '_')}_1"

            usage_label = str(occurrence.get("usage_label", "idiomatic")).strip().lower()
            if usage_label not in {"literal", "idiomatic"}:
                usage_label = "idiomatic"

            gloss = str(occurrence.get("gloss", "")).strip() or (
                "Expression extracted by LLM from input text context."
            )
            example = str(occurrence.get("sentence_text", "")).strip()
            if not example:
                example = str(occurrence.get("surface", "")).strip()

            try:
                expression_id = target.upsert_mwe_expression(
                    canonical_form=candidate,
                    expression_type=expression_type,
                    is_separable=bool(occurrence.get("is_separable", False)),
                    max_gap_tokens=self._settings.second_pass_max_gap_tokens,
                    base_lemma=base_lemma,
                    particle=particle,
                )
                target.upsert_mwe_sense(
                    expression_id=int(expression_id),
                    sense_key=sense_key,
                    gloss=gloss,
                    usage_label=usage_label,
                    example=example,
                    priority=10,
                )
                upserted += 1
            except Exception as exc:
                failed += 1
                self._log_error("upsert_mwe_records_from_occurrences.upsert", exc)

        save_fn = getattr(target, "save", None)
        if callable(save_fn):
            try:
                save_fn()
            except Exception as exc:
                self._log_error("upsert_mwe_records_from_occurrences.save", exc)

        duration_ms = (time.perf_counter() - stage_start) * 1000.0
        return {
            "status": "ok" if failed == 0 else ("partial" if upserted > 0 else "failed"),
            "reason": (
                domain_reasons.REASON_NONE
                if failed == 0
                else domain_reasons.REASON_MWE_UPSERT_ERRORS
            ),
            "duration_ms": round(duration_ms, 3),
            "upserted_count": upserted,
            "failed_count": failed,
            "candidate_count": len(seen),
            "request_id": request_id,
        }

    def _call_third_pass_extractor(
        self,
        *,
        text: str,
        request_id: str,
        think_mode: bool | None,
        enabled: bool,
        timeout_ms: int | None,
    ) -> Any:
        attempts: list[dict[str, Any]] = []
        with_timeout = (
            {
                "text": text,
                "request_id": request_id,
                "think_mode": think_mode,
                "enabled": enabled,
                "timeout_ms": timeout_ms,
            }
            if timeout_ms is not None
            else {
                "text": text,
                "request_id": request_id,
                "think_mode": think_mode,
                "enabled": enabled,
            }
        )
        attempts.append(with_timeout)
        attempts.extend(
            [
                {
                    "text": text,
                    "request_id": request_id,
                    "think_mode": think_mode,
                    "enabled": enabled,
                },
                {
                    "text": text,
                    "request_id": request_id,
                    "think_mode": think_mode,
                },
                {
                    "text": text,
                    "request_id": request_id,
                },
            ]
        )
        last_error: TypeError | None = None
        for kwargs in attempts:
            try:
                return self._repository.detect_third_pass(**kwargs)
            except TypeError as exc:
                if "unexpected keyword argument" in str(exc):
                    last_error = exc
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("third pass extractor call failed")

    def _resolve_mwe_repository_target(self) -> Any | None:
        repo = self._repository
        if (
            callable(getattr(repo, "upsert_mwe_expression", None))
            and callable(getattr(repo, "upsert_mwe_sense", None))
        ):
            return repo
        return None

    def _guess_phrasal_parts(self, candidate: str, expression_type: str) -> tuple[str, str]:
        if expression_type != "phrasal_verb":
            return "", ""
        parts = [item for item in candidate.split(" ") if item]
        if len(parts) < 2:
            return "", ""
        return parts[0], parts[-1]

    @staticmethod
    def _safe_float(value: object, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _log_error(self, operation: str, error: Exception) -> None:
        if self._log_error_callback is not None:
            self._log_error_callback(operation, error)
