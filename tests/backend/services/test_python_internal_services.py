from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.python_services.export_service import app as export_app
from backend.python_services.nlp_service import app as nlp_app


class _StubParseUseCase:
    def execute(self, *, text: str, sync: bool, third_pass_enabled: bool, think_mode: bool):
        payload = SimpleNamespace(
            table=[["1", "word", "word", "word", "General", "exact", "word", "1.0", "yes"]],
            summary={"tokens": 1},
            status_message=f"parsed:{text}",
            error_message="",
        )
        return SimpleNamespace(success=True, data=payload, error_message="")

    def close(self, timeout_seconds: float = 0.0):
        return None


class _StubSqliteRepository:
    def parse_mwe_text(self, text: str, **_: object):
        return {"text": text, "mode": "mwe"}

    def detect_third_pass(self, **kwargs: object):
        return {"mode": "third_pass", **kwargs}

    def pipeline_status(self):
        return {"status": "ok"}

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


class _StubAssignmentStore:
    def close(self):
        return None


class _StubExportService:
    def export_to_excel(self, request):
        request.output_path.write_bytes(b"xlsx")
        return SimpleNamespace(success=True, output_path=request.output_path, message="ok")


def _stub_components():
    return SimpleNamespace(
        parse_use_case=_StubParseUseCase(),
        lexicon_gateway=_StubSqliteRepository(),
        initialization_coordinator=_StubCoordinator(),
        llama_server_manager=_StubManager(),
    )


def test_nlp_parse_endpoint_serializes_rows():
    nlp_app.app.state.components = _stub_components()
    nlp_app.app.state.sentence_extractor = SimpleNamespace(
        extract_sentence=lambda text, term: f"{term}:{text}"
    )
    payload = nlp_app.parse_text(nlp_app.ParseRequest(text="Hello"))
    assert payload["rows"][0]["token"] == "word"
    assert payload["rows"][0]["index"] == 1
    assert payload["rows"][0]["confidence"] == "1.0"
    assert payload["rows"][0]["known"] == "true"
    assert payload["status_message"] == "parsed:Hello"


def test_export_service_returns_file_response():
    with patch.object(export_app, "_build_export_service", return_value=_StubExportService()):
        response = export_app.export_lexicon()
        assert response.status_code == 200
        assert response.filename == "lexicon_export.xlsx"
