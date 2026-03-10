from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from core.use_cases.parse_and_sync import ParseAndSyncInteractor, ParseSyncSettings
from infrastructure.adapters.lexicon_gateway import SqliteLexiconGateway
from infrastructure.config import PipelineSettings


class _DeterministicThirdPassGateway(SqliteLexiconGateway):
    def __init__(
        self,
        *,
        db_path: Path,
        settings: PipelineSettings,
        third_pass_payload: dict[str, Any],
    ) -> None:
        super().__init__(db_path=db_path, settings=settings)
        self._third_pass_payload = dict(third_pass_payload)
        self.third_pass_calls = 0

    def detect_third_pass(  # type: ignore[override]
        self,
        *,
        text: str,
        request_id: str,
        think_mode: bool | None = None,
        enabled: bool | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        del text, request_id, think_mode, enabled, timeout_ms
        self.third_pass_calls += 1
        return dict(self._third_pass_payload)


def _assert_stage_names(summary: dict[str, Any], expected: set[str]) -> None:
    stages = {
        str(item.get("stage"))
        for item in summary.get("stage_statuses", [])
        if isinstance(item, dict) and str(item.get("stage", "")).strip()
    }
    missing = expected - stages
    assert not missing, f"Missing stages: {sorted(missing)}; got={sorted(stages)}"


def _fetch_category_by_normalized(db_path: Path, normalized: str) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT category
            FROM lexicon_entries
            WHERE normalized = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
    return str(row[0]) if row is not None else None


def _fetch_registered_categories(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM lexicon_categories").fetchall()
    return {str(item[0]) for item in rows}


def _fetch_all_normalized_terms(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT normalized FROM lexicon_entries").fetchall()
    return {str(item[0]).strip().lower() for item in rows if str(item[0]).strip()}


def _seed_phrasal_expression_without_senses(gateway: SqliteLexiconGateway) -> None:
    gateway.upsert_mwe_expression(
        canonical_form="hand in",
        expression_type="phrasal_verb",
        is_separable=True,
        max_gap_tokens=4,
        base_lemma="hand",
        particle="in",
    )


def _seed_fill_in_expression_without_senses(gateway: SqliteLexiconGateway) -> None:
    gateway.upsert_mwe_expression(
        canonical_form="fill in",
        expression_type="phrasal_verb",
        is_separable=True,
        max_gap_tokens=4,
        base_lemma="fill",
        particle="in",
    )


@pytest.mark.timeout(180)
def test_real_pipeline_sync_adds_fill_in_as_phrasal_verb_with_expected_category(
    tmp_path: Path,
) -> None:
    settings = PipelineSettings.from_env()
    if not str(settings.spacy_trf_model_name).strip():
        pytest.skip("spaCy TRF model name is not configured")

    db_path = tmp_path / "real_pipeline_fill_in.sqlite3"
    gateway = SqliteLexiconGateway(db_path=db_path, settings=settings)
    try:
        _seed_fill_in_expression_without_senses(gateway)
        interactor = ParseAndSyncInteractor(
            repository=gateway,
            category_repository=gateway,
            settings=ParseSyncSettings(
                auto_sync_enabled=True,
                enable_second_pass_wsd=True,
                enable_third_pass_llm=False,
            ),
        )
        try:
            result = interactor.execute(
                "Please fill in the form now.",
                sync=True,
                third_pass_enabled=False,
            )
        finally:
            interactor.close()

        assert result.success is True
        assert result.data is not None
        summary = dict(result.data.summary)
        second_pass = dict(summary.get("second_pass", {}))
        _assert_stage_names(
            second_pass,
            expected={"mwe_index", "mwe_detect", "mwe_disambiguate"},
        )
        occurrences = second_pass.get("occurrences", [])
        assert isinstance(occurrences, list)
        assert any(
            isinstance(item, dict)
            and str(item.get("canonical_form", "")).strip().lower() == "fill in"
            and str(item.get("source", "")).strip().lower()
            in {"spacy_trf_semantic", "second_pass_spacy_semantic"}
            for item in occurrences
        )

        phrasal_category = _fetch_category_by_normalized(db_path, "fill in")
        assert phrasal_category == "Phrasal Verb"
        particle_category = _fetch_category_by_normalized(db_path, "in")
        assert particle_category == "Preposition"
        categories = _fetch_registered_categories(db_path)
        assert "Phrasal Verb" in categories
        assert "Preposition" in categories
    finally:
        gateway.close()


@pytest.mark.timeout(180)
def test_real_pipeline_sync_adds_phrasal_verb_with_expected_category(tmp_path: Path) -> None:
    settings = PipelineSettings.from_env()
    if not str(settings.spacy_trf_model_name).strip():
        pytest.skip("spaCy TRF model name is not configured")

    db_path = tmp_path / "real_pipeline_phrasal.sqlite3"
    gateway = SqliteLexiconGateway(db_path=db_path, settings=settings)
    try:
        _seed_phrasal_expression_without_senses(gateway)
        interactor = ParseAndSyncInteractor(
            repository=gateway,
            category_repository=gateway,
            settings=ParseSyncSettings(
                auto_sync_enabled=True,
                enable_second_pass_wsd=True,
                enable_third_pass_llm=False,
            ),
        )
        try:
            result = interactor.execute(
                "They hand forms in weekly.",
                sync=True,
                third_pass_enabled=False,
            )
        finally:
            interactor.close()

        assert result.success is True
        assert result.data is not None
        summary = dict(result.data.summary)

        _assert_stage_names(
            summary,
            expected={"tokenize", "exact_match", "lemma_inflect", "wordnet_match", "bert_match"},
        )
        second_pass = dict(summary.get("second_pass", {}))
        _assert_stage_names(
            second_pass,
            expected={"mwe_index", "mwe_detect", "mwe_disambiguate"},
        )

        phrasal_category = _fetch_category_by_normalized(db_path, "hand in")
        assert phrasal_category == "Phrasal Verb"
        categories = _fetch_registered_categories(db_path)
        assert "Phrasal Verb" in categories
    finally:
        gateway.close()


@pytest.mark.timeout(180)
def test_real_pipeline_runs_all_stages_and_syncs_phrasal_and_idiom_to_db(tmp_path: Path) -> None:
    settings = PipelineSettings.from_env()
    if not str(settings.spacy_trf_model_name).strip():
        pytest.skip("spaCy TRF model name is not configured")

    third_pass_payload = {
        "schema_version": 1,
        "enabled": True,
        "status": "ok",
        "reason": "",
        "model_info": {"backend": "deterministic_test_double"},
        "candidates_count": 1,
        "resolved_count": 1,
        "uncertain_count": 0,
        "occurrences": [
            {
                "surface": "spill the beans",
                "canonical_form": "spill the beans",
                "expression_type": "idiom",
                "is_separable": False,
                "sentence_text": "They hand forms in weekly, then spill the beans.",
                "score": 0.91,
                "usage_label": "idiomatic",
                "status": "resolved",
                "source": "third_pass_llm",
            }
        ],
        "stage_statuses": [
            {
                "stage": "llm_extract",
                "status": "ok",
                "reason": "",
                "duration_ms": 1.0,
                "metadata": {"provider": "deterministic_test_double"},
            }
        ],
        "cache_hit": False,
    }

    db_path = tmp_path / "real_pipeline_all_stages.sqlite3"
    gateway = _DeterministicThirdPassGateway(
        db_path=db_path,
        settings=settings,
        third_pass_payload=third_pass_payload,
    )
    try:
        _seed_phrasal_expression_without_senses(gateway)
        interactor = ParseAndSyncInteractor(
            repository=gateway,
            category_repository=gateway,
            settings=ParseSyncSettings(
                auto_sync_enabled=True,
                enable_second_pass_wsd=True,
                enable_third_pass_llm=True,
            ),
        )
        try:
            result = interactor.execute(
                "They hand forms in weekly, then spill the beans.",
                sync=True,
                third_pass_enabled=True,
            )
        finally:
            interactor.close()

        assert result.success is True
        assert result.data is not None
        summary = dict(result.data.summary)
        _assert_stage_names(
            summary,
            expected={"tokenize", "exact_match", "lemma_inflect", "wordnet_match", "bert_match"},
        )

        second_pass = dict(summary.get("second_pass", {}))
        _assert_stage_names(
            second_pass,
            expected={"mwe_index", "mwe_detect", "mwe_disambiguate"},
        )
        occurrences = second_pass.get("occurrences", [])
        assert isinstance(occurrences, list)
        assert any(
            isinstance(item, dict)
            and str(item.get("canonical_form", "")).strip().lower() == "hand in"
            and str(item.get("source", "")).strip().lower() == "spacy_trf_semantic"
            for item in occurrences
        )

        third_pass = dict(summary.get("third_pass", {}))
        _assert_stage_names(third_pass, expected={"llm_extract"})
        policy = dict(third_pass.get("validation_policy", {}))
        assert bool(policy.get("allowed", False)) is True
        assert str(policy.get("reason", "")) == "validation_suspicious_trf_uncertain"

        phrasal_category = _fetch_category_by_normalized(db_path, "hand in")
        idiom_category = _fetch_category_by_normalized(db_path, "spill the beans")
        assert phrasal_category == "Phrasal Verb"
        assert idiom_category == "Idiom"

        categories = _fetch_registered_categories(db_path)
        assert "Phrasal Verb" in categories
        assert "Idiom" in categories
    finally:
        gateway.close()


@pytest.mark.timeout(180)
def test_real_pipeline_allows_third_pass_fallback_without_seed_mwe(tmp_path: Path) -> None:
    settings = PipelineSettings.from_env()
    if not str(settings.spacy_trf_model_name).strip():
        pytest.skip("spaCy TRF model name is not configured")

    third_pass_payload = {
        "schema_version": 1,
        "enabled": True,
        "status": "ok",
        "reason": "",
        "model_info": {"backend": "deterministic_test_double"},
        "candidates_count": 1,
        "resolved_count": 1,
        "uncertain_count": 0,
        "occurrences": [
            {
                "surface": "spill the beans",
                "canonical_form": "spill the beans",
                "expression_type": "idiom",
                "is_separable": False,
                "sentence_text": "Let's call it a day and spill the beans.",
                "score": 0.93,
                "usage_label": "idiomatic",
                "status": "resolved",
                "source": "third_pass_llm",
            }
        ],
        "stage_statuses": [
            {
                "stage": "llm_extract",
                "status": "ok",
                "reason": "",
                "duration_ms": 1.0,
                "metadata": {"provider": "deterministic_test_double"},
            }
        ],
        "cache_hit": False,
    }

    db_path = tmp_path / "real_pipeline_cold_start_fallback.sqlite3"
    gateway = _DeterministicThirdPassGateway(
        db_path=db_path,
        settings=settings,
        third_pass_payload=third_pass_payload,
    )
    try:
        interactor = ParseAndSyncInteractor(
            repository=gateway,
            category_repository=gateway,
            settings=ParseSyncSettings(
                auto_sync_enabled=True,
                enable_second_pass_wsd=True,
                enable_third_pass_llm=True,
            ),
        )
        try:
            result = interactor.execute(
                "Let's call it a day and spill the beans.",
                sync=True,
                third_pass_enabled=True,
            )
        finally:
            interactor.close()

        assert result.success is True
        assert result.data is not None
        summary = dict(result.data.summary)
        second_pass = dict(summary.get("second_pass", {}))
        _assert_stage_names(
            second_pass,
            expected={"mwe_index", "mwe_detect", "mwe_disambiguate"},
        )
        third_pass = dict(summary.get("third_pass", {}))
        _assert_stage_names(third_pass, expected={"llm_extract"})
        policy = dict(third_pass.get("validation_policy", {}))
        assert bool(policy.get("allowed", False)) is True
        assert str(policy.get("reason", "")) == "validation_second_pass_empty_fallback"
        assert gateway.third_pass_calls == 1

        idiom_category = _fetch_category_by_normalized(db_path, "spill the beans")
        assert idiom_category == "Idiom"
    finally:
        gateway.close()


@pytest.mark.timeout(180)
def test_real_pipeline_regression_canonicalizes_and_avoids_known_false_phrasals(
    tmp_path: Path,
) -> None:
    settings = PipelineSettings.from_env()
    if not str(settings.spacy_trf_model_name).strip():
        pytest.skip("spaCy TRF model name is not configured")

    third_pass_payload = {
        "schema_version": 1,
        "enabled": True,
        "status": "ok",
        "reason": "",
        "model_info": {"backend": "deterministic_test_double"},
        "candidates_count": 2,
        "resolved_count": 2,
        "uncertain_count": 0,
        "occurrences": [
            {
                "surface": "ran into",
                "canonical_form": "ran into",
                "expression_type": "phrasal_verb",
                "is_separable": False,
                "sentence_text": "Yesterday we ran into an old friend.",
                "score": 0.92,
                "usage_label": "idiomatic",
                "status": "resolved",
                "source": "third_pass_llm",
            },
            {
                "surface": "called it a day",
                "canonical_form": "called it a day",
                "expression_type": "idiom",
                "is_separable": False,
                "sentence_text": "Then we called it a day.",
                "score": 0.9,
                "usage_label": "idiomatic",
                "status": "resolved",
                "source": "third_pass_llm",
            },
        ],
        "stage_statuses": [
            {
                "stage": "llm_extract",
                "status": "ok",
                "reason": "",
                "duration_ms": 1.0,
                "metadata": {"provider": "deterministic_test_double"},
            }
        ],
        "cache_hit": False,
    }

    db_path = tmp_path / "real_pipeline_regression.sqlite3"
    gateway = _DeterministicThirdPassGateway(
        db_path=db_path,
        settings=settings,
        third_pass_payload=third_pass_payload,
    )
    try:
        interactor = ParseAndSyncInteractor(
            repository=gateway,
            category_repository=gateway,
            settings=ParseSyncSettings(
                auto_sync_enabled=True,
                enable_second_pass_wsd=True,
                enable_third_pass_llm=True,
            ),
        )
        try:
            result = interactor.execute(
                "Yesterday we ran into an old friend. "
                "We carry this with pride and put the notes on the table. "
                "Then we called it a day.",
                sync=True,
                third_pass_enabled=True,
            )
        finally:
            interactor.close()

        assert result.success is True
        assert result.data is not None
        terms = _fetch_all_normalized_terms(db_path)
        assert "run into" in terms
        assert "call it a day" in terms
        assert "carry with" not in terms
        assert "put on" not in terms
    finally:
        gateway.close()
