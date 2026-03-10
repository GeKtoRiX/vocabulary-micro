from __future__ import annotations

from pathlib import Path

from core.domain import ExportRequest, ExportResult, Result
from core.domain import IExportService, ILoggingService
from core.use_cases._base import BaseInteractor


class ExportLexiconInteractor(BaseInteractor):
    def __init__(
        self,
        *,
        service: IExportService,
        logger: ILoggingService | None = None,
    ) -> None:
        self._service = service
        self._logger = logger

    def execute(self, output_path: Path) -> Result[ExportResult]:
        resolved_output = Path(output_path).expanduser()
        if resolved_output.suffix.lower() != ".xlsx":
            resolved_output = resolved_output.with_suffix(".xlsx")

        request = ExportRequest(output_path=resolved_output)
        try:
            payload = self._service.export_to_excel(request)
            if payload.success:
                result = Result.ok(payload, status_code="ok")
            else:
                result = Result.fail(payload.message, status_code="export_failed", data=payload)
            self._log_info(f"export_to_excel: success={result.success}, path={resolved_output}")
            return result
        except Exception as exc:
            self._log_error(operation="export_to_excel", error=exc)
            return Result.fail(
                f"Export failed: {exc}",
                status_code="export_exception",
                data=ExportResult(
                    success=False,
                    message=f"Export failed: {exc}",
                    output_path=resolved_output,
                    stats={},
                ),
            )


