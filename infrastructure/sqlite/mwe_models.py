from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SenseChoice:
    sense_id: int
    sense_key: str
    gloss: str
    usage_label: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sense_id": self.sense_id,
            "sense_key": self.sense_key,
            "gloss": self.gloss,
            "usage_label": self.usage_label,
            "score": round(float(self.score), 4),
        }


@dataclass(frozen=True)
class MweCandidate:
    expression_id: int
    canonical_form: str
    expression_type: str
    is_separable: bool
    span_start: int
    span_end: int
    token_start_index: int
    token_end_index: int
    surface: str
    sentence_text: str
    detection_source: str = "second_pass_spacy"
    semantic_score: float = 0.0
    semantic_boosted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "expression_id": self.expression_id,
            "canonical_form": self.canonical_form,
            "expression_type": self.expression_type,
            "is_separable": self.is_separable,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "token_start_index": self.token_start_index,
            "token_end_index": self.token_end_index,
            "surface": self.surface,
            "sentence_text": self.sentence_text,
            "detection_source": self.detection_source,
            "semantic_score": round(float(self.semantic_score), 4),
            "semantic_boosted": bool(self.semantic_boosted),
        }


@dataclass(frozen=True)
class MweOccurrence:
    surface: str
    canonical_form: str
    expression_type: str
    is_separable: bool
    span_start: int
    span_end: int
    sentence_text: str
    sense: SenseChoice | None
    alternatives: list[SenseChoice] = field(default_factory=list)
    score: float = 0.0
    margin: float = 0.0
    usage_label: str = "uncertain"
    status: str = "uncertain"
    source: str = "second_pass_spacy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "canonical_form": self.canonical_form,
            "expression_type": self.expression_type,
            "is_separable": self.is_separable,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "sentence_text": self.sentence_text,
            "sense": self.sense.to_dict() if self.sense is not None else None,
            "alternatives": [item.to_dict() for item in self.alternatives],
            "score": round(float(self.score), 4),
            "margin": round(float(self.margin), 4),
            "usage_label": self.usage_label,
            "status": self.status,
            "source": self.source,
        }


@dataclass(frozen=True)
class SecondPassSummary:
    enabled: bool
    status: str
    reason: str
    model_info: dict[str, Any]
    candidates_count: int
    resolved_count: int
    uncertain_count: int
    occurrences: list[MweOccurrence] = field(default_factory=list)
    stage_statuses: list[dict[str, Any]] = field(default_factory=list)
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "status": self.status,
            "reason": self.reason,
            "model_info": dict(self.model_info),
            "candidates_count": self.candidates_count,
            "resolved_count": self.resolved_count,
            "uncertain_count": self.uncertain_count,
            "occurrences": [item.to_dict() for item in self.occurrences],
            "stage_statuses": [dict(item) for item in self.stage_statuses],
            "cache_hit": self.cache_hit,
        }

