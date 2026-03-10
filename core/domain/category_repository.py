from __future__ import annotations

from abc import ABC, abstractmethod

from .models import CategoryMutationResult


class ICategoryRepository(ABC):
    @abstractmethod
    def list_categories(self) -> list[str]:
        """Return all category names available for lexicon entries."""

    @abstractmethod
    def create_category(self, name: str) -> CategoryMutationResult:
        """Create category if missing and return updated category metadata."""

    @abstractmethod
    def delete_category(self, name: str) -> CategoryMutationResult:
        """Delete category when possible and return updated category metadata."""
