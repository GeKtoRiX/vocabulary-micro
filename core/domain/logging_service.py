from __future__ import annotations

from abc import ABC, abstractmethod


class ILoggingService(ABC):
    @abstractmethod
    def info(self, message: str) -> None:
        """Write an informational log entry."""

    @abstractmethod
    def warning(self, message: str) -> None:
        """Write a warning log entry."""

    @abstractmethod
    def error(self, message: str) -> None:
        """Write an error log entry."""

    @abstractmethod
    def close(self) -> None:
        """Release logger resources."""
