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


def test_parse_reasoning_payload_extracts_candidates_when_content_is_empty() -> None:
    extractor = LlmThirdPassExtractor(settings=PipelineSettings())
    reasoning = """
Thinking Process:

2.  **Analyze the Input Text:**
    *   "look into": Phrasal verb meaning to investigate.
    *   "spill the beans": Idiom meaning to reveal a secret.
    *   "carry out": Phrasal verb meaning to perform or execute.

3.  **Evaluate Candidates:**
    *   "look into":
        *   Type: phrasal_verb.
        *   Usage: idiomatic.
        *   Gloss: investigate or examine.
        *   Confidence: High.
    *   "spill the beans":
        *   Type: idiom.
        *   Usage: idiomatic.
        *   Gloss: reveal a secret.
        *   Confidence: High.
"""

    parsed = extractor._parse_reasoning_payload(reasoning)  # noqa: SLF001
    assert isinstance(parsed, dict)

    normalized = extractor._normalize_occurrences(parsed)  # noqa: SLF001
    by_form = {str(item.get("canonical_form", "")): item for item in normalized}

    assert "look into" in by_form
    assert by_form["look into"]["expression_type"] == "phrasal_verb"
    assert "spill the beans" in by_form
    assert by_form["spill the beans"]["expression_type"] == "idiom"
    assert "carry out" in by_form
