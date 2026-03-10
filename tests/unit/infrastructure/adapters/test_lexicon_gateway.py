from __future__ import annotations

from pathlib import Path

import pytest

from core.domain import (
    CategoryMutationResult,
    ICategoryRepository,
    ILexiconRepository,
    LexiconDeleteRequest,
    LexiconMutationResult,
    LexiconQuery,
    LexiconUpdateRequest,
)
from infrastructure.adapters.lexicon_gateway import SqliteLexiconGateway


@pytest.fixture
def gateway_with_mocks(mocker: pytest.MockFixture):
    store = mocker.Mock()
    management = mocker.Mock()
    third_pass = mocker.Mock()

    mocker.patch("infrastructure.adapters.clean_sqlite_gateway.SqliteLexicon", return_value=store)
    mocker.patch(
        "infrastructure.adapters.clean_sqlite_gateway.SqliteLexiconManagementStore",
        return_value=management,
    )
    mocker.patch("infrastructure.adapters.clean_sqlite_gateway.LlmThirdPassExtractor", return_value=third_pass)

    gateway = SqliteLexiconGateway(db_path=Path("lexicon.sqlite3"), settings=object())
    return gateway, store, management, third_pass


def test_gateway_implements_interfaces(gateway_with_mocks) -> None:
    gateway, _, _, _ = gateway_with_mocks
    assert isinstance(gateway, ILexiconRepository)
    assert isinstance(gateway, ICategoryRepository)


def test_gateway_delegates_parse_and_write_operations(gateway_with_mocks) -> None:
    gateway, store, _, third_pass = gateway_with_mocks
    store.parse_text.return_value = {"tokens": []}
    store.parse_mwe_text.return_value = {"occurrences": []}
    store.pipeline_status.return_value = {"status": "ok"}
    third_pass.detect.return_value = {"occurrences": []}
    store.build_index.return_value = ({}, {})
    store.add_entry.return_value = "inserted"
    store.add_entries.return_value = ("a", "b")
    store.upsert_mwe_expression.return_value = 101
    store.upsert_mwe_sense.return_value = 202

    assert gateway.parse_text("hello", request_id="req-1") == {"tokens": []}
    assert gateway.parse_mwe_text("hello", request_id="req-1", top_n=0, enabled=True) == {"occurrences": []}
    assert gateway.pipeline_status() == {"status": "ok"}
    assert gateway.detect_third_pass(
        text="hello",
        request_id="req-1",
        think_mode=True,
        enabled=True,
        timeout_ms=1234,
    ) == {"occurrences": []}
    assert gateway.build_index() == ({}, {})
    assert gateway.add_entry("Verb", "run", source="auto", confidence=0.9, request_id="req-1") == "inserted"
    assert gateway.add_entries([("Verb", "run")], source="auto", confidence=0.9, request_id="req-1") == ["a", "b"]
    assert gateway.supports_mwe_upsert() is True
    assert gateway.upsert_mwe_expression(canonical_form="take off", expression_type="phrasal_verb") == 101
    assert gateway.upsert_mwe_sense(
        expression_id=101,
        sense_key="sense1",
        gloss="desc",
        usage_label="idiomatic",
    ) == 202
    gateway.close()

    store.parse_text.assert_called_once_with("hello", request_id="req-1")
    store.parse_mwe_text.assert_called_once_with("hello", request_id="req-1", top_n=1, enabled=True)
    third_pass.detect.assert_called_once_with(
        text="hello",
        request_id="req-1",
        think_mode=True,
        enabled=True,
        timeout_ms=1234,
    )
    store.close.assert_called_once()


def test_gateway_delegates_management_operations(gateway_with_mocks, sample_lexicon_search_result, sample_lexicon_entry) -> None:
    gateway, _, management, _ = gateway_with_mocks
    query = LexiconQuery(status="all", limit=50, offset=0)
    update_request = LexiconUpdateRequest(entry_id=1, status="approved", category="Verb", value="run")
    delete_request = LexiconDeleteRequest(entry_ids=[1, 2])

    management.search_entries.return_value = sample_lexicon_search_result
    management.get_entry.return_value = sample_lexicon_entry
    management.update_entry.return_value = LexiconMutationResult(success=True, message="updated", affected_count=1)
    management.delete_entries.return_value = LexiconMutationResult(success=True, message="deleted", affected_count=2)
    management.list_categories.return_value = ["Verb", "Noun"]
    management.create_category.return_value = CategoryMutationResult(categories=["Verb", "Noun"], message="created")
    management.delete_category.return_value = CategoryMutationResult(categories=["Verb"], message="deleted")

    assert gateway.search_entries(query) == sample_lexicon_search_result
    assert gateway.get_entry(1) == sample_lexicon_entry
    assert gateway.update_entry(update_request).message == "updated"
    assert gateway.delete_entries(delete_request).affected_count == 2
    assert gateway.list_categories() == ["Verb", "Noun"]
    assert gateway.create_category("Noun").message == "created"
    assert gateway.delete_category("Noun").message == "deleted"

    management.search_entries.assert_called_once_with(query)
    management.get_entry.assert_called_once_with(1)
    management.update_entry.assert_called_once_with(update_request)
    management.delete_entries.assert_called_once_with(delete_request)


def test_gateway_detect_third_pass_runs_preflight_hook(gateway_with_mocks) -> None:
    gateway, _, _, third_pass = gateway_with_mocks
    calls: list[str] = []
    gateway._third_pass_preflight = lambda: calls.append("preflight")  # type: ignore[attr-defined]
    third_pass.detect.return_value = {"occurrences": []}

    payload = gateway.detect_third_pass(text="hello", request_id="req-2")

    assert payload == {"occurrences": []}
    assert calls == ["preflight"]
    third_pass.detect.assert_called_once_with(
        text="hello",
        request_id="req-2",
        think_mode=None,
        enabled=None,
        timeout_ms=None,
    )
