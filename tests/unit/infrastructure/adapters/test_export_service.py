from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from core.domain import ExportRequest, IExportService
from infrastructure.adapters.export_service import HttpLexiconExportService, SqliteExcelExportService


def test_export_service_implements_interface(tmp_path: Path) -> None:
    service = SqliteExcelExportService(tmp_path / "lexicon.sqlite3")
    assert isinstance(service, IExportService)


def test_http_export_service_implements_interface() -> None:
    service = HttpLexiconExportService(base_url="http://lexicon-service:4011")
    assert isinstance(service, IExportService)


def test_export_to_excel_returns_error_when_sqlite_file_is_missing(tmp_path: Path) -> None:
    service = SqliteExcelExportService(tmp_path / "missing.sqlite3")

    result = service.export_to_excel(ExportRequest(output_path=tmp_path / "report.xlsx"))

    assert result.success is False
    assert "SQLite file not found" in result.message
    assert result.output_path == (tmp_path / "report.xlsx").resolve()
    assert result.stats["table_count"] == 0
    assert result.stats["row_count"] == 0


def test_export_to_excel_generates_workbook_from_sqlite_tables(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    db_path = tmp_path / "lexicon.sqlite3"
    output_path_without_suffix = tmp_path / "export_report"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE lexicon_entries (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO lexicon_entries (id, category, value)
            VALUES (1, 'Verb', 'run')
            """
        )
        conn.commit()

    service = SqliteExcelExportService(db_path)
    result = service.export_to_excel(ExportRequest(output_path=output_path_without_suffix))

    assert result.success is True
    assert result.output_path is not None
    assert result.output_path.suffix == ".xlsx"
    assert result.output_path.exists()
    assert result.stats["table_count"] == 1
    assert result.stats["row_count"] == 1
    assert result.stats["sheet_names"] == ["lexicon_entries"]

    workbook = openpyxl.load_workbook(result.output_path)
    sheet = workbook["lexicon_entries"]
    assert sheet["A1"].value == "id"
    assert sheet["B1"].value == "category"
    assert sheet["C1"].value == "value"
    assert sheet["A2"].value == 1
    assert sheet["B2"].value == "Verb"
    assert sheet["C2"].value == "run"


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
