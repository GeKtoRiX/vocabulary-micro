from __future__ import annotations

from core.domain import LexiconMutationResult, LexiconQuery
from core.use_cases.manage_lexicon import ManageLexiconInteractor


def test_search_returns_result_from_repository(
    mock_lexicon_repository,
    mock_category_repository,
    sample_lexicon_search_result,
) -> None:
    mock_lexicon_repository.search_entries.return_value = sample_lexicon_search_result
    interactor = ManageLexiconInteractor(
        lexicon_repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
    )
    query = LexiconQuery(status="approved", limit=10, offset=0)

    result = interactor.search(query)

    assert result.success is True
    assert result.data == sample_lexicon_search_result
    mock_lexicon_repository.search_entries.assert_called_once_with(query)


def test_search_returns_error_when_repository_raises(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.search_entries.side_effect = RuntimeError("db unavailable")
    interactor = ManageLexiconInteractor(
        lexicon_repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
    )

    result = interactor.search(LexiconQuery())

    assert result.success is False
    assert result.status_code == "search_exception"
    assert "db unavailable" in (result.error_message or "")


def test_update_entry_returns_ok_and_refreshes_search_payload(
    mock_lexicon_repository,
    mock_category_repository,
    sample_lexicon_search_result,
) -> None:
    mock_lexicon_repository.update_entry.return_value = LexiconMutationResult(
        success=True,
        message="Entry updated.",
        affected_count=1,
    )
    mock_lexicon_repository.search_entries.return_value = sample_lexicon_search_result
    interactor = ManageLexiconInteractor(
        lexicon_repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
    )
    query = LexiconQuery(status="all")

    result = interactor.update_entry(
        entry_id=7,
        status="approved",
        category="Verb",
        value="run",
        query=query,
    )

    assert result.success is True
    assert result.data is not None
    assert result.data.message == "Entry updated."
    update_request = mock_lexicon_repository.update_entry.call_args.args[0]
    assert update_request.entry_id == 7
    assert update_request.status == "approved"
    assert update_request.category == "Verb"
    assert update_request.value == "run"
    mock_lexicon_repository.search_entries.assert_called_once_with(query)


def test_update_entry_returns_fail_when_mutation_fails(
    mock_lexicon_repository,
    mock_category_repository,
    sample_lexicon_search_result,
) -> None:
    mock_lexicon_repository.update_entry.return_value = LexiconMutationResult(
        success=False,
        message="Update failed: invalid category.",
        affected_count=0,
    )
    mock_lexicon_repository.search_entries.return_value = sample_lexicon_search_result
    interactor = ManageLexiconInteractor(
        lexicon_repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
    )

    result = interactor.update_entry(
        entry_id=3,
        status="approved",
        category="Unknown",
        value="run",
        query=LexiconQuery(),
    )

    assert result.success is False
    assert result.status_code == "update_failed"
    assert result.data is not None
    assert result.data.message == "Update failed: invalid category."


def test_assign_category_returns_not_found_when_entry_missing(
    mock_lexicon_repository,
    mock_category_repository,
    sample_lexicon_search_result,
) -> None:
    mock_lexicon_repository.get_entry.return_value = None
    mock_lexicon_repository.search_entries.return_value = sample_lexicon_search_result
    interactor = ManageLexiconInteractor(
        lexicon_repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
    )

    result = interactor.assign_category(
        entry_id=999,
        category="Verb",
        query=LexiconQuery(),
    )

    assert result.success is False
    assert result.status_code == "assign_not_found"
    assert "not found" in (result.error_message or "").lower()
    assert result.data is not None
    assert "not found" in result.data.message.lower()


def test_delete_entries_returns_ok_when_repository_reports_success(
    mock_lexicon_repository,
    mock_category_repository,
    sample_lexicon_search_result,
) -> None:
    mock_lexicon_repository.delete_entries.return_value = LexiconMutationResult(
        success=True,
        message="Deleted 2 entries.",
        affected_count=2,
    )
    mock_lexicon_repository.search_entries.return_value = sample_lexicon_search_result
    interactor = ManageLexiconInteractor(
        lexicon_repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
    )

    result = interactor.delete_entries(entry_ids=[1, 2], query=LexiconQuery())

    assert result.success is True
    assert result.data is not None
    assert result.data.message == "Deleted 2 entries."


def test_category_operations_handle_business_failures_and_exceptions(
    mock_lexicon_repository,
    mock_category_repository,
    sample_category_mutation_result,
) -> None:
    interactor = ManageLexiconInteractor(
        lexicon_repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
    )

    mock_category_repository.create_category.return_value = sample_category_mutation_result
    create_ok = interactor.create_category("Noun")
    assert create_ok.success is True

    mock_category_repository.create_category.return_value = sample_category_mutation_result.__class__(
        categories=[],
        message="Create failed: category must not be empty.",
    )
    create_fail = interactor.create_category("")
    assert create_fail.success is False
    assert create_fail.status_code == "create_category_failed"

    mock_category_repository.delete_category.side_effect = RuntimeError("db locked")
    delete_fail = interactor.delete_category("Noun")
    assert delete_fail.success is False
    assert delete_fail.status_code == "delete_category_exception"
    assert "db locked" in (delete_fail.error_message or "")
