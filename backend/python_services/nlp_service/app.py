from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from infrastructure.sqlite.assignment_sentence_extractor import AssignmentSentenceExtractor
from backend.python_services.nlp_service.components import build_nlp_components


class ParseRequest(BaseModel):
    text: str
    sync: bool = False
    third_pass_enabled: bool = False
    think_mode: bool = False


class ParseMweRequest(BaseModel):
    text: str
    request_id: str | None = None
    top_n: int = 3
    enabled: bool | None = None


class ThirdPassRequest(BaseModel):
    text: str
    request_id: str
    think_mode: bool | None = None
    enabled: bool | None = None
    timeout_ms: int | None = None


class ExtractSentenceRequest(BaseModel):
    text: str
    term: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    components = build_nlp_components()
    app.state.components = components
    app.state.sentence_extractor = AssignmentSentenceExtractor()
    yield
    try:
        components.parse_use_case.close(timeout_seconds=5.0)
    except Exception:
        pass
    try:
        components.llama_server_manager.close()
    except Exception:
        pass


app = FastAPI(title="Vocabulary NLP Service", lifespan=lifespan)


def _components():
    return app.state.components


def _serialize_parse_result(payload: Any) -> dict[str, Any]:
    rows = []
    columns = ["token", "normalized", "lemma", "categories", "source", "matched_form", "confidence", "known"]
    for fallback_index, row in enumerate(payload.table, start=1):
        values = list(row)
        if len(values) >= len(columns) + 1:
            raw_index = values[0]
            values = values[1:]
        else:
            raw_index = fallback_index

        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = fallback_index

        entry = {"index": index}
        for column, value in zip(columns, values):
            if column == "known":
                normalized = str(value).strip().lower()
                if normalized in {"yes", "true", "1"}:
                    entry[column] = "true"
                elif normalized in {"no", "false", "0"}:
                    entry[column] = "false"
                else:
                    entry[column] = str(value)
                continue
            entry[column] = "" if value is None else str(value)
        for column in columns:
            entry.setdefault(column, "")
        rows.append(entry)
    return {
        "rows": rows,
        "summary": payload.summary,
        "status_message": payload.status_message,
        "error_message": payload.error_message,
    }


@app.get("/internal/v1/system/health")
def health():
    return {"status": "ok"}


@app.get("/internal/v1/system/warmup")
def warmup_status():
    snap = _components().initialization_coordinator.snapshot()
    elapsed: float | None = None
    if snap.started_at is not None and snap.finished_at is not None:
        elapsed = round(snap.finished_at - snap.started_at, 2)
    elif snap.started_at is not None:
        import time
        elapsed = round(time.perf_counter() - snap.started_at, 2)
    return {
        "running": snap.running,
        "ready": snap.ready,
        "failed": snap.failed,
        "error_message": snap.error_message,
        "elapsed_sec": elapsed,
    }


@app.post("/internal/v1/nlp/parse")
def parse_text(req: ParseRequest):
    result = _components().parse_use_case.execute(
        text=req.text,
        sync=req.sync,
        third_pass_enabled=req.third_pass_enabled,
        think_mode=req.think_mode,
    )
    if not result.success or result.data is None:
        return {
            "rows": [],
            "summary": {},
            "status_message": "",
            "error_message": result.error_message or "Parse failed.",
        }
    return _serialize_parse_result(result.data)


@app.post("/internal/v1/nlp/parse-mwe")
def parse_mwe(req: ParseMweRequest):
    return _components().lexicon_gateway.parse_mwe_text(
        req.text,
        request_id=req.request_id,
        top_n=req.top_n,
        enabled=req.enabled,
    )


@app.post("/internal/v1/nlp/third-pass")
def third_pass(req: ThirdPassRequest):
    return _components().lexicon_gateway.detect_third_pass(
        text=req.text,
        request_id=req.request_id,
        think_mode=req.think_mode,
        enabled=req.enabled,
        timeout_ms=req.timeout_ms,
    )


@app.get("/internal/v1/nlp/pipeline-status")
def pipeline_status():
    return _components().lexicon_gateway.pipeline_status()


@app.post("/internal/v1/nlp/extract-sentence")
def extract_sentence(req: ExtractSentenceRequest):
    return {
        "sentence": app.state.sentence_extractor.extract_sentence(
            text=req.text,
            term=req.term,
        )
    }
