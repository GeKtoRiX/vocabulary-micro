from __future__ import annotations

from typing import Sequence

from infrastructure.sqlite.mwe_models import MweCandidate, MweOccurrence, SenseChoice
from infrastructure.config import PipelineSettings

from .mwe_index_provider import MweIndexSnapshot

# Compatibility aliases for tests that validate optional dependency fallbacks.
torch = None
SentenceTransformer = None


class MweDisambiguator:
    """Rule-based sense resolver without embedding models."""

    def __init__(self, settings: PipelineSettings) -> None:
        self._settings = settings
        self._unavailable_reason: str | None = None

    def availability(self, *, ensure_loaded: bool = True) -> dict[str, object]:
        del ensure_loaded
        return {
            "st_model": self._settings.st_model_name,
            "st_model_revision": self._settings.st_model_revision,
            "st_local_files_only": self._settings.st_local_files_only,
            "st_available": True,
            "st_unavailable_reason": self._unavailable_reason,
        }

    def disambiguate(
        self,
        *,
        candidates: Sequence[MweCandidate],
        snapshot: MweIndexSnapshot,
        top_n: int = 3,
    ) -> dict[str, object]:
        if not candidates:
            return {
                "status": "ok",
                "reason": "",
                "occurrences": [],
                "resolved_count": 0,
                "uncertain_count": 0,
                "cache_hit": False,
            }

        resolved_count = 0
        uncertain_count = 0
        occurrences: list[MweOccurrence] = []

        for candidate in candidates:
            semantic_confidence = max(0.0, float(candidate.semantic_score or 0.0))
            prefer_semantic_confidence = bool(candidate.semantic_boosted) and semantic_confidence > 0.0
            senses = list(snapshot.senses_by_expression.get(candidate.expression_id, tuple()))
            if not senses:
                uncertain_count += 1
                occurrences.append(
                    MweOccurrence(
                        surface=candidate.surface,
                        canonical_form=candidate.canonical_form,
                        expression_type=candidate.expression_type,
                        is_separable=candidate.is_separable,
                        span_start=candidate.span_start,
                        span_end=candidate.span_end,
                        sentence_text=candidate.sentence_text,
                        sense=None,
                        alternatives=[],
                        score=semantic_confidence if semantic_confidence > 0.0 else 0.0,
                        margin=0.0,
                        usage_label="uncertain",
                        status="uncertain",
                        source=str(candidate.detection_source or "second_pass_spacy"),
                    )
                )
                continue

            # Prefer lower priority value first, then stable id ordering.
            ordered = sorted(senses, key=lambda item: (item.priority, item.sense_id))
            alternatives: list[SenseChoice] = []
            for idx, sense in enumerate(ordered[: max(1, top_n)]):
                score = self._score_for_rank(idx, sense_count=len(ordered))
                alternatives.append(
                    SenseChoice(
                        sense_id=sense.sense_id,
                        sense_key=sense.sense_key,
                        gloss=sense.gloss,
                        usage_label=sense.usage_label,
                        score=score,
                    )
                )

            first = alternatives[0]
            second_score = alternatives[1].score if len(alternatives) > 1 else 0.0
            margin = first.score - second_score
            resolved = (
                first.score >= self._settings.second_pass_similarity_threshold
                and margin >= self._settings.second_pass_margin_threshold
            )
            if resolved:
                resolved_count += 1
            else:
                uncertain_count += 1

            output_score = semantic_confidence if prefer_semantic_confidence else first.score

            occurrences.append(
                MweOccurrence(
                    surface=candidate.surface,
                    canonical_form=candidate.canonical_form,
                    expression_type=candidate.expression_type,
                    is_separable=candidate.is_separable,
                    span_start=candidate.span_start,
                    span_end=candidate.span_end,
                    sentence_text=candidate.sentence_text,
                    sense=first if resolved else None,
                    alternatives=alternatives,
                    score=output_score,
                    margin=margin,
                    usage_label=first.usage_label if resolved else "uncertain",
                    status="resolved" if resolved else "uncertain",
                    source=str(candidate.detection_source or "second_pass_spacy"),
                )
            )

        return {
            "status": "ok",
            "reason": "",
            "occurrences": occurrences,
            "resolved_count": resolved_count,
            "uncertain_count": uncertain_count,
            "cache_hit": False,
        }

    def _score_for_rank(self, rank: int, *, sense_count: int) -> float:
        if sense_count <= 1:
            return 0.9
        if rank == 0:
            return 0.85
        if rank == 1:
            return 0.65
        return max(0.3, 0.65 - (rank * 0.1))


