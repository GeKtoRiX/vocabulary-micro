from __future__ import annotations

from infrastructure.adapters.llm_third_pass import LlmThirdPassExtractor
from infrastructure.config import PipelineSettings


def test_normalize_occurrences_canonicalizes_inflected_forms() -> None:
    extractor = LlmThirdPassExtractor(settings=PipelineSettings())
    payload = {
        "occurrences": [
            {
                "canonical_form": "ran into",
                "expression_type": "phrasal_verb",
                "usage_label": "idiomatic",
                "confidence": 0.88,
            },
            {
                "canonical_form": "called it a day",
                "expression_type": "idiom",
                "usage_label": "idiomatic",
                "confidence": 0.9,
            },
        ]
    }

    normalized = extractor._normalize_occurrences(payload)  # noqa: SLF001
    forms = {str(item.get("canonical_form", "")) for item in normalized}

    assert "run into" in forms
    assert "call it a day" in forms
    assert "ran into" not in forms
    assert "called it a day" not in forms
