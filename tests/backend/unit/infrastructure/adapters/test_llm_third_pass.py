from __future__ import annotations

import json

import pytest

import backend.python_services.infrastructure.adapters.llm_third_pass as llm_third_pass_module
from backend.python_services.infrastructure.adapters.llm_third_pass import LlmThirdPassExtractor
from backend.python_services.infrastructure.config import PipelineSettings


class _FakeStreamingResponse:
    def __init__(self, *lines: str) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self) -> "_FakeStreamingResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def __iter__(self):
        return iter(self._lines)


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


def test_build_prompt_enforces_strict_c1_classification_rules() -> None:
    extractor = LlmThirdPassExtractor(settings=PipelineSettings())

    prompt = extractor._build_prompt(  # noqa: SLF001
        text="He came up with a plan but had bitten off more than he could chew.",
        think_mode=False,
    )

    assert "came up with" in prompt
    assert "let them down" in prompt
    assert "bite off more than one can chew" in prompt
    assert "If unsure, omit the candidate." in prompt
    assert 'If there are no valid candidates, return {"occurrences": []}.' in prompt


def test_parse_reasoning_payload_extracts_c1_phrasal_verbs_and_idioms() -> None:
    extractor = LlmThirdPassExtractor(settings=PipelineSettings())
    reasoning = """
Evaluation:
* "come up with": Phrasal verb meaning to produce or suggest.
* "let down": Phrasal verb meaning to disappoint.
* "bite off more than one can chew": Idiom meaning to take on too much.
* "pull through": Phrasal verb meaning to recover successfully.
"""

    parsed = extractor._parse_reasoning_payload(reasoning)  # noqa: SLF001
    assert isinstance(parsed, dict)

    normalized = extractor._normalize_occurrences(parsed)  # noqa: SLF001
    by_form = {str(item.get("canonical_form", "")): item for item in normalized}

    assert by_form["come up with"]["expression_type"] == "phrasal_verb"
    assert by_form["let down"]["expression_type"] == "phrasal_verb"
    assert by_form["bite off more than one can chew"]["expression_type"] == "idiom"
    assert by_form["pull through"]["expression_type"] == "phrasal_verb"


@pytest.mark.parametrize(
    ("think_mode", "expected_prefix"),
    [
        (True, "/think"),
        (False, "/no_think"),
    ],
)
def test_request_llm_switches_reasoning_mode_in_payload(
    monkeypatch: pytest.MonkeyPatch,
    think_mode: bool,
    expected_prefix: str,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        captured["timeout"] = timeout
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeStreamingResponse(
            'data: {"choices":[{"delta":{"content":"{\\"occurrences\\":[]}"}}]}\n',
            "data: [DONE]\n",
        )

    monkeypatch.setattr(llm_third_pass_module.urllib_request, "urlopen", fake_urlopen)

    extractor = LlmThirdPassExtractor(
        settings=PipelineSettings(
            third_pass_llm_base_url="http://127.0.0.1:8000",
            third_pass_llm_model="Qwen3.5-9B-GGUF",
            third_pass_llm_timeout_ms=60000,
            third_pass_llm_think_mode=False,
        )
    )

    payload = extractor._request_llm(  # noqa: SLF001
        text="He came up with a plan.",
        think_mode=think_mode,
        timeout_ms=None,
    )

    assert payload == {"occurrences": []}
    request_payload = captured["payload"]
    assert isinstance(request_payload, dict)
    assert request_payload["chat_template_kwargs"] == {"enable_thinking": think_mode}
    assert request_payload["stream"] is True
    messages = request_payload["messages"]
    assert isinstance(messages, list)
    assert messages[1]["content"].startswith(expected_prefix)
