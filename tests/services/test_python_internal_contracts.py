from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import jsonschema
import yaml

from python_services import nlp_app


def _load_openapi() -> dict:
    path = Path(__file__).resolve().parents[2] / "services" / "contracts" / "internal-v1.openapi.yaml"
    return yaml.safe_load(path.read_text("utf-8"))


def _validate_component(name: str, payload: object) -> None:
    document = _load_openapi()
    schema = document["components"]["schemas"][name]
    resolver = jsonschema.RefResolver.from_schema(document)
    jsonschema.validate(payload, schema, resolver=resolver)


class _StubParseUseCase:
    def execute(self, *, text: str, sync: bool, third_pass_enabled: bool, think_mode: bool):
        del sync, third_pass_enabled, think_mode
        payload = SimpleNamespace(
            table=[["1", "word", "word", "word", "General", "exact", "word", "1.0", "yes"]],
            summary={"tokens": 1},
            status_message=f"parsed:{text}",
            error_message="",
        )
        return SimpleNamespace(success=True, data=payload, error_message="")

    def close(self, timeout_seconds: float = 0.0):
        return None


class _StubLexiconGateway:
    def parse_mwe_text(self, text: str, **_: object):
        return {
            "status": "ok",
            "pipeline_status": "ready",
            "occurrences": [{"canonical_form": text.lower(), "matched_text": text, "expression_type": "idiom", "score": 0.9}],
            "pipeline": {"ready": True},
            "stage_statuses": [],
        }

    def detect_third_pass(self, **kwargs: object):
        return {
            "enabled": True,
            "status": "ok",
            "reason": "",
            "occurrences": [kwargs],
            "candidates_count": 1,
            "resolved_count": 1,
            "uncertain_count": 0,
            "stage_statuses": [],
        }

    def pipeline_status(self):
        return {"ready": True, "status": "ok", "model": "stub"}

    def close(self):
        return None


class _StubCoordinator:
    def snapshot(self):
        return SimpleNamespace(
            running=False,
            ready=True,
            failed=False,
            error_message="",
            started_at=None,
            finished_at=None,
        )


class _StubManager:
    def close(self):
        return None


def _stub_components():
    return SimpleNamespace(
        parse_use_case=_StubParseUseCase(),
        lexicon_gateway=_StubLexiconGateway(),
        initialization_coordinator=_StubCoordinator(),
        llama_server_manager=_StubManager(),
    )


def test_python_internal_contracts_follow_openapi() -> None:
    nlp_app.app.state.components = _stub_components()
    nlp_app.app.state.sentence_extractor = SimpleNamespace(
        extract_sentence=lambda text, term: f"{term}:{text}"
    )

    warmup = nlp_app.warmup_status()
    parse_payload = nlp_app.parse_text(nlp_app.ParseRequest(text="Hello"))
    mwe_payload = nlp_app.parse_mwe(nlp_app.ParseMweRequest(text="fill in"))
    third_pass_payload = nlp_app.third_pass(nlp_app.ThirdPassRequest(text="fill in", request_id="req-1"))
    pipeline = nlp_app.pipeline_status()
    sentence = nlp_app.extract_sentence(nlp_app.ExtractSentenceRequest(text="I run every day.", term="run"))

    _validate_component("WarmupStatus", warmup)
    _validate_component("ParseResult", parse_payload)
    _validate_component("MweParseResult", mwe_payload)
    _validate_component("ThirdPassResult", third_pass_payload)
    _validate_component("PipelineStatus", pipeline)
    _validate_component("ExtractSentenceResult", sentence)
