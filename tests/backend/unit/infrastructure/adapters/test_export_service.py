from __future__ import annotations

from pathlib import Path

import pytest

from backend.python_services.core.domain import ExportRequest
from backend.python_services.infrastructure.adapters.http_export_service import HttpLexiconExportService


def test_http_export_to_excel_generates_workbook_from_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    service = HttpLexiconExportService(base_url="http://lexicon-service:4011")

    monkeypatch.setattr(
        service,
        "_fetch_snapshot",
        lambda: {
            "tables": [
                {
                    "name": "lexicon_entries",
                    "columns": ["id", "category", "value"],
                    "rows": [[1, "Verb", "run"]],
                },
                {
                    "name": "lexicon_categories",
                    "columns": ["name"],
                    "rows": [["Verb"]],
                },
            ]
        },
    )

    result = service.export_to_excel(ExportRequest(output_path=tmp_path / "snapshot_report"))

    assert result.success is True
    assert result.output_path is not None
    assert result.output_path.suffix == ".xlsx"
    assert result.output_path.exists()
    assert result.stats["table_count"] == 2
    assert result.stats["row_count"] == 2

    workbook = openpyxl.load_workbook(result.output_path)
    sheet = workbook["lexicon_entries"]
    assert sheet["A1"].value == "id"
    assert sheet["B1"].value == "category"
    assert sheet["C1"].value == "value"
    assert sheet["A2"].value == 1
    assert sheet["B2"].value == "Verb"
    assert sheet["C2"].value == "run"
