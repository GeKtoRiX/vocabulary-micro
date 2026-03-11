from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from backend.python_services.core.domain import ILoggingService


class FileLoggingService(ILoggingService):
    def __init__(self, file_path: Path) -> None:
        self._file_path = Path(file_path)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def info(self, message: str) -> None:
        self._write(level="INFO", message=message)

    def warning(self, message: str) -> None:
        self._write(level="WARNING", message=message)

    def error(self, message: str) -> None:
        self._write(level="ERROR", message=message)

    def close(self) -> None:
        # File handles are scoped per write operation; kept for lifecycle symmetry.
        return None

    def _write(self, *, level: str, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"{timestamp}\t{level}\t{str(message).strip()}\n"
        with self._lock:
            with self._file_path.open("a", encoding="utf-8") as handle:
                handle.write(line)

