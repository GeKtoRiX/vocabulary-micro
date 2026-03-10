from __future__ import annotations

import time
from typing import Any

from infrastructure.config import PipelineSettings
from infrastructure.sqlite.mwe_models import SecondPassSummary

from .mwe_candidate_detector import MweCandidateDetector
from .mwe_disambiguator import MweDisambiguator
from .mwe_index_provider import MweIndexProvider


class MweSecondPassEngine:
    def __init__(
        self,
        *,
        settings: PipelineSettings,
        index_provider: MweIndexProvider,
    ) -> None:
        self._settings = settings
        self._index_provider = index_provider
        self._detector = MweCandidateDetector(settings)
        self._disambiguator = MweDisambiguator(settings)

    def pipeline_status(self) -> dict[str, Any]:
        return self._model_info(ensure_loaded=True)

    def _model_info(
        self,
        *,
        ensure_loaded: bool,
        mwe_version: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": self._settings.enable_second_pass_wsd,
            **self._detector.availability(ensure_loaded=ensure_loaded),
            **self._disambiguator.availability(ensure_loaded=ensure_loaded),
        }
        if mwe_version is not None:
            payload["mwe_version"] = int(mwe_version)
        return payload

    def parse(
        self,
        text: str,
        *,
        request_id: str | None = None,
        top_n: int = 3,
        enabled: bool | None = None,
        preparsed_doc=None,
    ) -> dict[str, Any]:
        should_run = self._settings.enable_second_pass_wsd if enabled is None else bool(enabled)
        if not should_run:
            return SecondPassSummary(
                enabled=False,
                status="skipped",
                reason="second_pass_disabled",
                model_info=self.pipeline_status(),
                candidates_count=0,
                resolved_count=0,
                uncertain_count=0,
                occurrences=[],
                stage_statuses=[],
                cache_hit=False,
            ).to_dict()

        started = time.perf_counter()
        stage_statuses: list[dict[str, Any]] = []
        snapshot, index_cache_hit = self._index_provider.get_snapshot(
            model_name=self._settings.st_model_name,
            model_revision=self._settings.st_model_revision,
        )
        stage_statuses.append(
            {
                "stage": "mwe_index",
                "status": "ok",
                "reason": "",
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "metadata": {
                    "cache_hit": index_cache_hit,
                    "mwe_version": snapshot.version,
                },
            }
        )

        seed_expression_count = len(snapshot.expressions)
        detect_start = time.perf_counter()
        detection = self._detector.detect(
            text=text,
            snapshot=snapshot,
            request_id=request_id,
            preparsed_doc=preparsed_doc,
        )
        candidates = detection.get("candidates", [])
        used_preparsed_doc = bool(detection.get("used_preparsed_doc", False))

        stage_statuses.append(
            {
                "stage": "mwe_detect",
                "status": str(detection.get("status", "ok")),
                "reason": str(detection.get("reason", "")),
                "duration_ms": round((time.perf_counter() - detect_start) * 1000.0, 3),
                "metadata": {
                    "candidates_count": len(candidates),
                    "seed_expression_count": seed_expression_count,
                    "used_preparsed_doc": used_preparsed_doc,
                },
            }
        )
        if str(detection.get("status", "ok")) != "ok":
            return SecondPassSummary(
                enabled=True,
                status="skipped",
                reason=str(detection.get("reason", "detect_failed")),
                model_info=self._model_info(
                    ensure_loaded=not used_preparsed_doc,
                    mwe_version=snapshot.version,
                ),
                candidates_count=0,
                resolved_count=0,
                uncertain_count=0,
                occurrences=[],
                stage_statuses=stage_statuses,
                cache_hit=index_cache_hit,
            ).to_dict()

        disambiguate_start = time.perf_counter()
        wsd = self._disambiguator.disambiguate(
            candidates=candidates,
            snapshot=snapshot,
            top_n=max(1, top_n),
        )
        occurrences = list(wsd.get("occurrences", []))
        stage_statuses.append(
            {
                "stage": "mwe_disambiguate",
                "status": str(wsd.get("status", "ok")),
                "reason": str(wsd.get("reason", "")),
                "duration_ms": round((time.perf_counter() - disambiguate_start) * 1000.0, 3),
                "metadata": {
                    "resolved_count": int(wsd.get("resolved_count", 0)),
                    "uncertain_count": int(wsd.get("uncertain_count", 0)),
                    "cache_hit": bool(wsd.get("cache_hit", False)),
                },
            }
        )

        status = "ok"
        reason = ""
        if str(wsd.get("status", "ok")) != "ok":
            status = "partial"
            reason = str(wsd.get("reason", "wsd_partial"))
        return SecondPassSummary(
            enabled=True,
            status=status,
            reason=reason,
            model_info=self._model_info(
                ensure_loaded=not used_preparsed_doc,
                mwe_version=snapshot.version,
            ),
            candidates_count=len(candidates),
            resolved_count=int(wsd.get("resolved_count", 0)),
            uncertain_count=int(wsd.get("uncertain_count", 0)),
            occurrences=occurrences,
            stage_statuses=stage_statuses,
            cache_hit=index_cache_hit and bool(wsd.get("cache_hit", False)),
        ).to_dict()

    def release_request_resources(self, request_id: str | None) -> None:
        self._detector.release_request_cache(request_id)

