from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from core.domain import ExportRequest
from infrastructure.adapters.http_export_service import HttpLexiconExportService


app = FastAPI(title="Vocabulary Export Service")


def _lexicon_service_base_url() -> str:
    explicit = os.getenv("LEXICON_SERVICE_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = os.getenv("LEXICON_SERVICE_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("LEXICON_SERVICE_PORT", "4011").strip() or "4011"
    return f"http://{host}:{port}"


def _build_export_service() -> HttpLexiconExportService:
    timeout_sec = float(os.getenv("EXPORT_SERVICE_TIMEOUT_SEC", "30").strip() or "30")
    return HttpLexiconExportService(
        base_url=_lexicon_service_base_url(),
        timeout_sec=timeout_sec,
    )


@app.get("/internal/v1/system/health")
def health():
    return {"status": "ok"}


@app.get("/internal/v1/export/lexicon.xlsx")
def export_lexicon():
    fd, raw_path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    tmp_path = Path(raw_path)
    result = _build_export_service().export_to_excel(ExportRequest(output_path=tmp_path))
    if result.success and result.output_path and Path(result.output_path).exists():
        return FileResponse(
            path=str(result.output_path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="lexicon_export.xlsx",
            background=BackgroundTask(lambda: Path(result.output_path).unlink(missing_ok=True)),
        )
    raise HTTPException(status_code=500, detail=result.message)
