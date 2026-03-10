from __future__ import annotations

from core.domain import CategoryMutationResult
from core.use_cases.manage_categories import (
    CreateCategoryInteractor,
    DeleteCategoryInteractor,
    ListCategoriesInteractor,
)


def test_list_categories_returns_repository_values(mock_category_repository) -> None:
    interactor = ListCategoriesInteractor(mock_category_repository)

    result = interactor.execute()

    assert result.success is True
    assert result.data == ["Noun", "Verb"]


def test_create_category_returns_fail_for_business_failure_message(mock_category_repository) -> None:
    mock_category_repository.create_category.return_value = CategoryMutationResult(
        categories=["Noun", "Verb"],
        message="Create category skipped: name must not be empty.",
    )
    interactor = CreateCategoryInteractor(mock_category_repository)

    result = interactor.execute("")

    assert result.success is False
    assert result.status_code == "create_category_failed"
    assert result.data is not None
    assert "skipped" in result.data.message.lower()


def test_create_category_allows_idempotent_already_exists(mock_category_repository) -> None:
    mock_category_repository.create_category.return_value = CategoryMutationResult(
        categories=["Noun", "Verb"],
        message="Category 'Verb' already exists.",
    )
    interactor = CreateCategoryInteractor(mock_category_repository)

    result = interactor.execute("Verb")

    assert result.success is True
    assert result.data is not None
    assert "already exists" in result.data.message


def test_delete_category_returns_fail_for_not_found(mock_category_repository) -> None:
    mock_category_repository.delete_category.return_value = CategoryMutationResult(
        categories=["Noun", "Verb"],
        message="Category 'Adverb' not found.",
    )
    interactor = DeleteCategoryInteractor(mock_category_repository)

    result = interactor.execute("Adverb")

    assert result.success is False
    assert result.status_code == "delete_category_failed"
    assert result.data is not None
    assert "not found" in result.data.message.lower()


def test_delete_category_returns_exception_failure(mock_category_repository) -> None:
    mock_category_repository.delete_category.side_effect = RuntimeError("database down")
    interactor = DeleteCategoryInteractor(mock_category_repository)

    result = interactor.execute("Verb")

    assert result.success is False
    assert result.status_code == "delete_category_exception"
    assert "database down" in (result.error_message or "")
