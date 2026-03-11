from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any

from backend.python_services.core.domain import ILoggingService


DEFAULT_MAX_LOG_BYTES = 10 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 5

_CONFIG_LOCK = Lock()
_CONFIGURED_LOG_PATH: Path | None = None


def _to_serializable(value: Any) -> Any:
    if isinstance(value, (set, tuple)):
        return list(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


class _StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": int(record.lineno),
        }
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=_to_serializable, ensure_ascii=True)


def configure_app_logger(
    file_path: Path,
    *,
    level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_LOG_BYTES,
    backup_count: int = DEFAULT_LOG_BACKUP_COUNT,
) -> logging.Logger:
    global _CONFIGURED_LOG_PATH

    resolved_file_path = Path(file_path).expanduser().resolve()
    resolved_file_path.parent.mkdir(parents=True, exist_ok=True)

    with _CONFIG_LOCK:
        root_logger = logging.getLogger()
        already_configured = (
            _CONFIGURED_LOG_PATH == resolved_file_path and len(root_logger.handlers) >= 2
        )
        if already_configured:
            root_logger.setLevel(level)
            return root_logger

        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                continue

        formatter = _StructuredJsonFormatter()
        file_handler = RotatingFileHandler(
            filename=resolved_file_path,
            maxBytes=max(1, int(max_bytes)),
            backupCount=max(1, int(backup_count)),
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        root_logger.setLevel(level)
        root_logger.propagate = False
        _CONFIGURED_LOG_PATH = resolved_file_path
        return root_logger


def get_app_logger(name: str = "app") -> logging.Logger:
    return logging.getLogger(name)


class AppLoggingService(ILoggingService):
    def __init__(self, file_path: Path, *, logger_name: str = "app") -> None:
        configure_app_logger(file_path)
        self._logger = get_app_logger(logger_name)

    def info(self, message: str) -> None:
        self._logger.info(str(message).strip())

    def warning(self, message: str) -> None:
        self._logger.warning(str(message).strip())

    def error(self, message: str) -> None:
        self._logger.error(str(message).strip())

    def close(self) -> None:
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            try:
                handler.flush()
                if isinstance(handler, RotatingFileHandler):
                    handler.close()
            except Exception:
                continue
