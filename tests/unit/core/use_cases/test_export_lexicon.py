from __future__ import annotations

from pathlib import Path

from core.domain import ExportResult
from core.use_cases.export_lexicon import ExportLexiconInteractor


def test_execute_success_normalizes_output_suffix(mock_export_service) -> None:
    interactor = ExportLexiconInteractor(service=mock_export_service)

    result = interactor.execute(Path("reports/final_export"))

    assert result.success is True
    assert result.status_code == "ok"
    request = mock_export_service.export_to_excel.call_args.args[0]
    assert request.output_path.suffix == ".xlsx"
    assert request.output_path == Path("reports/final_export.xlsx")


def test_execute_returns_export_failed_when_service_reports_failure(mock_export_service, tmp_path: Path) -> None:
    mock_export_service.export_to_excel.return_value = ExportResult(
        success=False,
        message="Disk quota exceeded.",
        output_path=tmp_path / "out.xlsx",
        stats={},
    )
    interactor = ExportLexiconInteractor(service=mock_export_service)

    result = interactor.execute(tmp_path / "out.xlsx")

    assert result.success is False
    assert result.status_code == "export_failed"
    assert result.error_message == "Disk quota exceeded."
    assert result.data is not None
    assert result.data.output_path == tmp_path / "out.xlsx"


def test_execute_returns_export_exception_when_service_raises(mock_export_service, tmp_path: Path) -> None:
    mock_export_service.export_to_excel.side_effect = RuntimeError("permission denied")
    interactor = ExportLexiconInteractor(service=mock_export_service)

    result = interactor.execute(tmp_path / "report")

    assert result.success is False
    assert result.status_code == "export_exception"
    assert "permission denied" in (result.error_message or "")
    assert result.data is not None
    assert result.data.success is False
    assert result.data.output_path == tmp_path / "report.xlsx"
