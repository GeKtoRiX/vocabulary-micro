from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.domain import ExportRequest, ExportResult

try:
    from openpyxl import Workbook
except Exception:  # pragma: no cover - optional dependency at runtime
    Workbook = None


def _resolve_output_path(request: ExportRequest) -> Path:
    resolved_output_path = Path(request.output_path).expanduser().resolve()
    if resolved_output_path.suffix.lower() != ".xlsx":
        resolved_output_path = resolved_output_path.with_suffix(".xlsx")
    return resolved_output_path


def _base_stats(*, output_path: Path, **extra: Any) -> dict[str, Any]:
    return {
        "output_path": str(output_path),
        "table_count": 0,
        "row_count": 0,
        "sheet_names": [],
        **extra,
    }


def _render_workbook_from_snapshots(
    *,
    table_snapshots: list[dict[str, Any]],
    output_path: Path,
    base_stats: dict[str, Any],
) -> ExportResult:
    if Workbook is None:
        return ExportResult(
            success=False,
            message="Excel export is unavailable: install 'openpyxl'.",
            output_path=output_path,
            stats=base_stats,
        )

    workbook = Workbook()
    active_sheet = workbook.active
    used_titles: set[str] = set()
    sheet_names: list[str] = []
    total_rows = 0

    if not table_snapshots:
        active_sheet.title = _excel_sheet_title("empty", used_titles)
        active_sheet.append(["message"])
        active_sheet.append(["No exportable tables found."])
        sheet_names.append(active_sheet.title)
    else:
        workbook.remove(active_sheet)
        for snapshot in table_snapshots:
            sheet_title = _excel_sheet_title(str(snapshot.get("name", "Sheet")), used_titles)
            sheet = workbook.create_sheet(title=sheet_title)
            column_names = [str(column) for column in snapshot.get("columns", [])]
            rows = snapshot.get("rows", [])
            if not column_names:
                sheet.append(["value"])
                sheet_names.append(sheet_title)
                continue
            sheet.append(column_names)

            table_row_count = 0
            for row in rows:
                table_row_count += 1
                if isinstance(row, list):
                    values = row
                elif isinstance(row, tuple):
                    values = list(row)
                else:
                    values = [row]
                sheet.append([_safe_excel_cell(value) for value in values])
            total_rows += table_row_count
            sheet_names.append(sheet_title)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output_path)
    except OSError as exc:
        return ExportResult(
            success=False,
            message=f"Excel export failed (io): {exc}",
            output_path=output_path,
            stats=base_stats,
        )

    stats = {
        **base_stats,
        "table_count": len(sheet_names),
        "row_count": total_rows,
        "sheet_names": sheet_names,
    }
    return ExportResult(
        success=True,
        message=f"Exported {len(sheet_names)} table(s), {total_rows} row(s) to {output_path}.",
        output_path=output_path,
        stats=stats,
    )


def _excel_sheet_title(value: str, used_titles: set[str]) -> str:
    base = re.sub(r"[\\/*?:\[\]]", "_", str(value).strip()).strip("'")
    base = base or "Sheet"
    title = base[:31]
    suffix = 2
    while title in used_titles:
        suffix_text = f"_{suffix}"
        title = f"{base[: max(1, 31 - len(suffix_text))]}{suffix_text}"
        suffix += 1
    used_titles.add(title)
    return title


def _safe_excel_cell(value: object) -> object:
    if isinstance(value, memoryview):
        return f"<BLOB {len(value.tobytes())} bytes>"
    if isinstance(value, (bytes, bytearray)):
        return f"<BLOB {len(value)} bytes>"
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class HttpLexiconExportService:
    """Export adapter that consumes lexicon snapshots over the internal HTTP API."""

    def __init__(self, *, base_url: str, timeout_sec: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec

    def export_to_excel(self, request: ExportRequest) -> ExportResult:
        resolved_output_path = _resolve_output_path(request)
        base_stats = _base_stats(
            output_path=resolved_output_path,
            source="lexicon-service",
            source_base_url=self._base_url,
        )

        try:
            snapshot = self._fetch_snapshot()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            return ExportResult(
                success=False,
                message=f"Excel export failed (http {exc.code}): {detail or exc.reason}",
                output_path=resolved_output_path,
                stats=base_stats,
            )
        except (URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            return ExportResult(
                success=False,
                message=f"Excel export failed (snapshot): {exc}",
                output_path=resolved_output_path,
                stats=base_stats,
            )

        tables = snapshot.get("tables", [])
        if not isinstance(tables, list):
            return ExportResult(
                success=False,
                message="Excel export failed (snapshot): invalid 'tables' payload.",
                output_path=resolved_output_path,
                stats=base_stats,
            )
        return _render_workbook_from_snapshots(
            table_snapshots=[table for table in tables if isinstance(table, dict)],
            output_path=resolved_output_path,
            base_stats=base_stats,
        )

    def _fetch_snapshot(self) -> dict[str, Any]:
        request = Request(
            url=f"{self._base_url}/internal/v1/lexicon/export-snapshot",
            method="GET",
            headers={"Accept": "application/json"},
        )
        with urlopen(request, timeout=self._timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("snapshot response must be a JSON object")
        return payload
