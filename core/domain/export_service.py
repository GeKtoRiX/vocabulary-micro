from __future__ import annotations

from abc import ABC, abstractmethod

from .models import ExportRequest, ExportResult


class IExportService(ABC):
    @abstractmethod
    def export_to_excel(self, request: ExportRequest) -> ExportResult:
        """Export lexicon state into an Excel workbook."""
