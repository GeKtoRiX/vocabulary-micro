from __future__ import annotations

from core.domain import CategoryMutationResult, Result
from core.domain import ICategoryRepository


def _is_category_mutation_failure(message: str) -> bool:
    text = str(message or "").strip().casefold()
    if not text:
        return False
    failure_markers = ("failed", "must not be empty", "skipped", "not found")
    return any(marker in text for marker in failure_markers)


class ListCategoriesInteractor:
    def __init__(self, repository: ICategoryRepository) -> None:
        self._repository = repository

    def execute(self) -> Result[list[str]]:
        try:
            return Result.ok(self._repository.list_categories())
        except Exception as exc:
            return Result.fail(f"List categories failed: {exc}", status_code="categories_exception")


class CreateCategoryInteractor:
    def __init__(self, repository: ICategoryRepository) -> None:
        self._repository = repository

    def execute(self, name: str) -> Result[CategoryMutationResult]:
        try:
            payload = self._repository.create_category(name)
            if _is_category_mutation_failure(payload.message):
                return Result.fail(
                    payload.message,
                    status_code="create_category_failed",
                    data=payload,
                )
            return Result.ok(payload)
        except Exception as exc:
            return Result.fail(f"Create category failed: {exc}", status_code="create_category_exception")


class DeleteCategoryInteractor:
    def __init__(self, repository: ICategoryRepository) -> None:
        self._repository = repository

    def execute(self, name: str) -> Result[CategoryMutationResult]:
        try:
            payload = self._repository.delete_category(name)
            if _is_category_mutation_failure(payload.message):
                return Result.fail(
                    payload.message,
                    status_code="delete_category_failed",
                    data=payload,
                )
            return Result.ok(payload)
        except Exception as exc:
            return Result.fail(f"Delete category failed: {exc}", status_code="delete_category_exception")


