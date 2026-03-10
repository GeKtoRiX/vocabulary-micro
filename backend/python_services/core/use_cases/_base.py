from __future__ import annotations

import traceback

from core.domain import ILoggingService


class BaseInteractor:
    """Shared logging helpers for use-case interactors."""

    _logger: ILoggingService | None

    def _log_info(self, message: str) -> None:
        if self._logger is None:
            return
        self._logger.info(message)

    def _log_error(self, *, operation: str, error: Exception) -> None:
        if self._logger is None:
            return
        self._logger.error(
            f"operation={operation} error={error} traceback={traceback.format_exc()}"
        )
