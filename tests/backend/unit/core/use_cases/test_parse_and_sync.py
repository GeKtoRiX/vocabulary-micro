from __future__ import annotations

import backend.python_services.core.domain.reason_codes as domain_reasons

from backend.python_services.core.domain import ParseAndSyncResultDTO, ParseRowSyncResultDTO
from backend.python_services.core.use_cases.parse_and_sync import ParseAndSyncInteractor, ParseSyncSettings


def test_execute_returns_error_dto_for_empty_text(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=True,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.execute("   ")

    assert result.success is False
    assert result.status_code == "empty_text"
    assert result.error_message == "Enter English text for parsing."
    assert isinstance(result.data, ParseAndSyncResultDTO)
    assert result.data.table == []
    assert result.data.summary["sync_enabled"] is True
    mock_lexicon_repository.parse_text.assert_not_called()


def test_execute_returns_parse_failed_when_repository_returns_error(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.parse_text.return_value = {"error": "pipeline unavailable"}
    mock_lexicon_repository.pipeline_status.return_value = {"status": "down"}

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.execute("Hello world")

    assert result.success is False
    assert result.status_code == "parse_failed"
    assert isinstance(result.data, ParseAndSyncResultDTO)
    assert result.data.error_message == "pipeline unavailable"
    assert result.data.summary["pipeline"] == {"status": "down"}
    assert result.data.summary["pipeline_status"] == "failed"


def test_execute_success_returns_expected_dto(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.return_value = sample_parse_payload
    mock_lexicon_repository.build_index.return_value = (
        {"run": ["Verb"]},
        {("take", "off"): ["Phrasal Verb"]},
    )

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.execute("Run fast")

    assert result.success is True
    assert result.status_code == "ok"
    assert isinstance(result.data, ParseAndSyncResultDTO)
    assert len(result.data.table) == 2
    assert result.data.table[0][1] == "Run"
    assert result.data.table[0][8] == "yes"
    assert result.data.summary["sync_enabled"] is False
    assert result.data.summary["pipeline_status"] == "ok"
    assert "request_id" in result.data.summary
    mock_lexicon_repository.add_entries.assert_not_called()
    mock_lexicon_repository.add_entry.assert_not_called()
    mock_lexicon_repository.save.assert_not_called()


def test_execute_uses_backward_compatible_parse_signature(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.side_effect = [
        TypeError("unexpected keyword argument 'request_id'"),
        sample_parse_payload,
    ]
    mock_lexicon_repository.build_index.return_value = ({}, {})

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.execute("Run fast")

    assert result.success is True
    assert mock_lexicon_repository.parse_text.call_count == 2
    assert "request_id" in mock_lexicon_repository.parse_text.call_args_list[0].kwargs
    assert mock_lexicon_repository.parse_text.call_args_list[1].args == ("Run fast",)


def test_execute_rejects_invalid_extracted_candidates_from_third_pass(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.return_value = sample_parse_payload
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_lexicon_repository.parse_mwe_text.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [
            {
                "canonical_form": "fill in",
                "surface": "fill data in",
                "expression_type": "phrasal_verb",
                "source": "spacy_trf_semantic",
                "score": 0.55,
                "status": "uncertain",
            }
        ],
    }
    mock_lexicon_repository.detect_third_pass.return_value = {
        "occurrences": [
            {"canonical_form": "###", "expression_type": "idiom"},
            {"canonical_form": "x", "expression_type": "idiom"},
        ]
    }

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=True,
            enable_third_pass_llm=True,
        ),
    )

    result = interactor.execute("Some text", third_pass_enabled=True)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    assert "###" in result.data.summary["rejected_candidates"]
    assert "x" in result.data.summary["rejected_candidates"]
    assert result.data.summary["third_pass"]["enabled"] is True
    mock_lexicon_repository.detect_third_pass.assert_called_once()


def test_execute_adds_llm_phrasal_verb_rows_to_parse_table(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.return_value = sample_parse_payload
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_lexicon_repository.parse_mwe_text.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [
            {
                "canonical_form": "fill in",
                "surface": "fill data in",
                "expression_type": "phrasal_verb",
                "source": "spacy_trf_semantic",
                "score": 0.6,
                "status": "uncertain",
            }
        ],
    }
    mock_lexicon_repository.detect_third_pass.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [
            {
                "canonical_form": "fill in",
                "surface": "fill in",
                "expression_type": "phrasal_verb",
                "usage_label": "idiomatic",
                "score": 0.94,
            }
        ],
    }

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=True,
            enable_third_pass_llm=True,
        ),
    )

    result = interactor.execute("Fill in the form", third_pass_enabled=True)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    assert any(
        row[1] == "fill in"
        and row[4] == "Phrasal Verb"
        and row[5] == "third_pass_llm"
        for row in result.data.table
    )
    mock_lexicon_repository.detect_third_pass.assert_called_once()


def test_execute_blocks_third_pass_when_second_pass_trf_confidence_is_high(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.return_value = sample_parse_payload
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_lexicon_repository.parse_mwe_text.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [
            {
                "canonical_form": "fill in",
                "surface": "fill data in",
                "expression_type": "phrasal_verb",
                "source": domain_reasons.TRF_SEMANTIC_SOURCE,
                "score": 0.92,
                "status": "uncertain",
            }
        ],
    }
    mock_lexicon_repository.detect_third_pass.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [
            {
                "canonical_form": "fill in",
                "surface": "fill in",
                "expression_type": "phrasal_verb",
            }
        ],
    }

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=True,
            enable_third_pass_llm=True,
        ),
    )

    result = interactor.execute("Fill in the form", third_pass_enabled=True)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    third_pass = result.data.summary.get("third_pass", {})
    assert isinstance(third_pass, dict)
    assert third_pass.get("status") == "skipped"
    assert third_pass.get("reason") == domain_reasons.REASON_VALIDATION_BLOCKED_HIGH_CONFIDENCE_TRF
    mock_lexicon_repository.detect_third_pass.assert_not_called()


def test_execute_allows_third_pass_on_threshold_boundary_when_trf_is_uncertain(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.return_value = sample_parse_payload
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_lexicon_repository.parse_mwe_text.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [
            {
                "canonical_form": "fill in",
                "surface": "fill data in",
                "expression_type": "phrasal_verb",
                "source": domain_reasons.TRF_SEMANTIC_SOURCE,
                "score": ParseSyncSettings().trf_confidence_threshold,
                "status": "uncertain",
            }
        ],
    }
    mock_lexicon_repository.detect_third_pass.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [],
    }

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=True,
            enable_third_pass_llm=True,
        ),
    )

    result = interactor.execute("Fill in the form", third_pass_enabled=True)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    third_pass = result.data.summary.get("third_pass", {})
    assert isinstance(third_pass, dict)
    assert third_pass.get("validation_policy", {}).get("reason") == (
        domain_reasons.REASON_VALIDATION_SUSPICIOUS_TRF_UNCERTAIN
    )
    mock_lexicon_repository.detect_third_pass.assert_called_once()


def test_execute_allows_third_pass_when_second_pass_occurrences_are_empty(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.return_value = sample_parse_payload
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_lexicon_repository.parse_mwe_text.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [],
    }
    mock_lexicon_repository.detect_third_pass.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [],
    }

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=True,
            enable_third_pass_llm=True,
        ),
    )

    result = interactor.execute("Fill in the form", third_pass_enabled=True)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    third_pass = result.data.summary.get("third_pass", {})
    assert isinstance(third_pass, dict)
    assert third_pass.get("validation_policy", {}).get("reason") == (
        domain_reasons.REASON_VALIDATION_SECOND_PASS_EMPTY_FALLBACK
    )
    mock_lexicon_repository.detect_third_pass.assert_called_once()


def test_execute_allows_third_pass_when_second_pass_has_no_trf_signal(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.return_value = sample_parse_payload
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_lexicon_repository.parse_mwe_text.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [
            {
                "canonical_form": "hand in",
                "surface": "hand forms in",
                "expression_type": "phrasal_verb",
                "source": "second_pass_spacy",
                "score": 0.61,
                "status": "resolved",
            }
        ],
    }
    mock_lexicon_repository.detect_third_pass.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [],
    }

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=True,
            enable_third_pass_llm=True,
        ),
    )

    result = interactor.execute("They hand forms in weekly.", third_pass_enabled=True)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    third_pass = result.data.summary.get("third_pass", {})
    assert isinstance(third_pass, dict)
    assert third_pass.get("validation_policy", {}).get("reason") == (
        domain_reasons.REASON_VALIDATION_NO_TRF_SIGNAL_FALLBACK
    )
    mock_lexicon_repository.detect_third_pass.assert_called_once()


def test_execute_adds_heuristic_phrasal_row_when_second_and_third_pass_have_no_occurrences(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.parse_text.return_value = {
        "tokens": [
            {
                "token": "Fill",
                "normalized": "fill",
                "lemma": "fill",
                "pos": "VERB",
                "categories": ["Verb"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "in",
                "normalized": "in",
                "lemma": "in",
                "pos": "ADP",
                "categories": ["Preposition"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
        ],
        "stats": {
            "tokens_total": 2,
            "known_tokens": 0,
            "unknown_tokens": 2,
            "coverage_percent": 0.0,
            "source_counts": {"none": 2},
        },
        "phrase_matches": [],
        "pipeline": {"status": "ok"},
        "stage_statuses": [],
        "pipeline_status": "ok",
    }
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_lexicon_repository.parse_mwe_text.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [],
    }
    mock_lexicon_repository.detect_third_pass.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [],
    }

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=True,
            enable_third_pass_llm=True,
        ),
    )

    result = interactor.execute("Fill in", third_pass_enabled=True)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    assert any(
        row[1] == "fill in"
        and row[4] == "Phrasal Verb"
        and row[5] == "phrasal_heuristic"
        for row in result.data.table
    )


def test_execute_adds_heuristic_phrasal_row_for_non_adjacent_gap_particle(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.parse_text.return_value = {
        "tokens": [
            {
                "token": "Fill",
                "normalized": "fill",
                "lemma": "fill",
                "pos": "VERB",
                "categories": ["Verb"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "data",
                "normalized": "data",
                "lemma": "data",
                "pos": "NOUN",
                "categories": ["Noun"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "in",
                "normalized": "in",
                "lemma": "in",
                "pos": "ADP",
                "categories": ["Preposition"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
        ],
        "stats": {
            "tokens_total": 3,
            "known_tokens": 0,
            "unknown_tokens": 3,
            "coverage_percent": 0.0,
            "source_counts": {"none": 3},
        },
        "phrase_matches": [],
        "pipeline": {"status": "ok"},
        "stage_statuses": [],
        "pipeline_status": "ok",
    }
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_lexicon_repository.parse_mwe_text.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [],
    }
    mock_lexicon_repository.detect_third_pass.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [],
    }

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.execute("Fill data in", third_pass_enabled=False)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    assert any(
        row[1] == "fill in"
        and row[4] == "Phrasal Verb"
        and row[5] == "phrasal_heuristic"
        for row in result.data.table
    )


def test_execute_adds_heuristic_phrasal_row_for_run_into_particle(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.parse_text.return_value = {
        "tokens": [
            {
                "token": "Ran",
                "normalized": "ran",
                "lemma": "run",
                "pos": "VERB",
                "categories": ["Verb"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "into",
                "normalized": "into",
                "lemma": "into",
                "pos": "ADP",
                "categories": ["Preposition"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
        ],
        "stats": {
            "tokens_total": 2,
            "known_tokens": 0,
            "unknown_tokens": 2,
            "coverage_percent": 0.0,
            "source_counts": {"none": 2},
        },
        "phrase_matches": [],
        "pipeline": {"status": "ok"},
        "stage_statuses": [],
        "pipeline_status": "ok",
    }
    mock_lexicon_repository.build_index.return_value = ({}, {})

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.execute("Ran into", third_pass_enabled=False)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    assert any(
        row[1] == "run into"
        and row[4] == "Phrasal Verb"
        and row[5] == "phrasal_heuristic"
        for row in result.data.table
    )


def test_execute_skips_false_positive_heuristic_pairs_for_with_and_gap_on_patterns(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.parse_text.return_value = {
        "tokens": [
            {
                "token": "We",
                "normalized": "we",
                "lemma": "we",
                "pos": "PRON",
                "categories": ["Pronoun"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "carry",
                "normalized": "carry",
                "lemma": "carry",
                "pos": "VERB",
                "categories": ["Verb"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "this",
                "normalized": "this",
                "lemma": "this",
                "pos": "PRON",
                "categories": ["Pronoun"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "with",
                "normalized": "with",
                "lemma": "with",
                "pos": "ADP",
                "categories": ["Preposition"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "pride",
                "normalized": "pride",
                "lemma": "pride",
                "pos": "NOUN",
                "categories": ["Noun"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "and",
                "normalized": "and",
                "lemma": "and",
                "pos": "CCONJ",
                "categories": ["Coordinating conjunction"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "put",
                "normalized": "put",
                "lemma": "put",
                "pos": "VERB",
                "categories": ["Verb"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "the",
                "normalized": "the",
                "lemma": "the",
                "pos": "DET",
                "categories": ["Determiner"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "notes",
                "normalized": "notes",
                "lemma": "note",
                "pos": "NOUN",
                "categories": ["Noun"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "on",
                "normalized": "on",
                "lemma": "on",
                "pos": "ADP",
                "categories": ["Preposition"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "table",
                "normalized": "table",
                "lemma": "table",
                "pos": "NOUN",
                "categories": ["Noun"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
        ],
        "stats": {
            "tokens_total": 11,
            "known_tokens": 0,
            "unknown_tokens": 11,
            "coverage_percent": 0.0,
            "source_counts": {"none": 11},
        },
        "phrase_matches": [],
        "pipeline": {"status": "ok"},
        "stage_statuses": [],
        "pipeline_status": "ok",
    }
    mock_lexicon_repository.build_index.return_value = ({}, {})

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.execute(
        "We carry this with pride and put the notes on the table.",
        third_pass_enabled=False,
    )

    assert result.success is True
    assert result.data is not None
    assert not any(
        row[4] == "Phrasal Verb" and row[2] in {"carry with", "put on"}
        for row in result.data.table
    )


def test_execute_sync_persists_particle_token_with_preposition_category(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.parse_text.return_value = {
        "tokens": [
            {
                "token": "Fill",
                "normalized": "fill",
                "lemma": "fill",
                "pos": "VERB",
                "categories": ["Verb"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
            {
                "token": "in",
                "normalized": "in",
                "lemma": "in",
                "pos": "ADP",
                "categories": ["Preposition"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            },
        ],
        "stats": {
            "tokens_total": 2,
            "known_tokens": 0,
            "unknown_tokens": 2,
            "coverage_percent": 0.0,
            "source_counts": {"none": 2},
        },
        "phrase_matches": [],
        "pipeline": {"status": "ok"},
        "stage_statuses": [],
        "pipeline_status": "ok",
    }
    mock_lexicon_repository.build_index.return_value = ({}, {})

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=True,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.execute("Fill in", sync=True, third_pass_enabled=False)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    entries = mock_lexicon_repository.add_entries.call_args.kwargs["entries"]
    assert ("Preposition", "in") in entries
    assert ("Phrasal Verb", "fill in") in entries
    created_categories = [call.args[0] for call in mock_category_repository.create_category.call_args_list]
    assert "Preposition" in created_categories


def test_execute_sync_auto_creates_missing_pos_category(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.parse_text.return_value = {
        "tokens": [
            {
                "token": "Hello",
                "normalized": "hello",
                "lemma": "hello",
                "pos": "INTJ",
                "categories": ["Interjection"],
                "match_source": "none",
                "matched_form": "",
                "bert_score": None,
            }
        ],
        "stats": {
            "tokens_total": 1,
            "known_tokens": 0,
            "unknown_tokens": 1,
            "coverage_percent": 0.0,
            "source_counts": {"none": 1},
        },
        "phrase_matches": [],
        "pipeline": {"status": "ok"},
        "stage_statuses": [],
        "pipeline_status": "ok",
    }
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_category_repository.list_categories.return_value = ["Auto Added"]

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=True,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.execute("Hello", sync=True, third_pass_enabled=False)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    entries = mock_lexicon_repository.add_entries.call_args.kwargs["entries"]
    assert ("Interjection", "hello") in entries
    created_categories = [call.args[0] for call in mock_category_repository.create_category.call_args_list]
    assert "Interjection" in created_categories


def test_parse_and_sync_defaults_empty_auto_add_category_to_auto_added(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        auto_add_category="   ",
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    assert interactor.auto_add_category == "Auto Added"


def test_execute_sync_merges_inflected_aliases_for_third_pass_candidates(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.return_value = sample_parse_payload
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_lexicon_repository.parse_mwe_text.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [],
    }
    mock_lexicon_repository.detect_third_pass.return_value = {
        "enabled": True,
        "status": "ok",
        "occurrences": [
            {
                "canonical_form": "ran into",
                "expression_type": "phrasal_verb",
                "usage_label": "idiomatic",
                "score": 0.89,
            },
            {
                "canonical_form": "run into",
                "expression_type": "phrasal_verb",
                "usage_label": "idiomatic",
                "score": 0.91,
            },
            {
                "canonical_form": "called it a day",
                "expression_type": "idiom",
                "usage_label": "idiomatic",
                "score": 0.9,
            },
        ],
    }

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=True,
            enable_second_pass_wsd=True,
            enable_third_pass_llm=True,
        ),
    )

    result = interactor.execute(
        "Yesterday we ran into an old friend and called it a day.",
        sync=True,
        third_pass_enabled=True,
    )

    assert result.success is True
    assert result.data is not None
    entries = mock_lexicon_repository.add_entries.call_args.kwargs["entries"]
    assert entries.count(("Phrasal Verb", "run into")) == 1
    assert ("Idiom", "call it a day") in entries
    assert ("Phrasal Verb", "ran into") not in entries


def test_sync_single_row_returns_result_payload_on_success(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.build_index.return_value = ({}, {})
    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.sync_single_row(
        token="Run",
        normalized="run",
        lemma="run",
        categories="Verb",
    )

    assert result.success is True
    assert isinstance(result.data, ParseRowSyncResultDTO)
    assert result.data.status == "added"
    mock_lexicon_repository.add_entry.assert_called_once()
    mock_lexicon_repository.save.assert_called_once()


def test_sync_single_row_prefers_normalized_phrase_and_keeps_phrasal_category(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_category_repository.list_categories.return_value = ["Verb", "Noun", "Auto Added"]
    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.sync_single_row(
        token="fill data in",
        normalized="fill in",
        lemma="fill",
        categories="Phrasal Verb",
    )

    assert result.success is True
    assert isinstance(result.data, ParseRowSyncResultDTO)
    assert result.data.value == "fill in"
    assert result.data.category == "Phrasal Verb"
    mock_category_repository.create_category.assert_called_once_with("Phrasal Verb")
    kwargs = mock_lexicon_repository.add_entry.call_args.kwargs
    assert kwargs["value"] == "fill in"
    assert kwargs["category"] == "Phrasal Verb"


def test_sync_single_row_returns_failure_result_for_empty_candidate(
    mock_lexicon_repository,
    mock_category_repository,
) -> None:
    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=False,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
        ),
    )

    result = interactor.sync_single_row(
        token="",
        normalized="",
        lemma="",
        categories="Verb",
    )

    assert result.success is False
    assert result.status_code == "row_rejected"
    assert isinstance(result.data, ParseRowSyncResultDTO)
    assert result.data.status == "rejected"


def test_execute_uses_persistent_queue_factory_when_enabled(
    mock_lexicon_repository,
    mock_category_repository,
    sample_parse_payload,
) -> None:
    mock_lexicon_repository.parse_text.return_value = sample_parse_payload
    mock_lexicon_repository.build_index.return_value = ({}, {})
    mock_category_repository.list_categories.return_value = ["Verb", "Adverb"]

    class _StubQueue:
        def __init__(self) -> None:
            self.enqueued = 0

        def enqueue(self, job):  # noqa: ANN001
            self.enqueued += 1
            return True, self.enqueued

        @property
        def depth(self) -> int:
            return 0

        def wait_for_idle(self, timeout_seconds: float = 2.0) -> bool:  # noqa: ARG002
            return True

        def shutdown(self, *, drain: bool = True, timeout_seconds: float = 2.0):  # noqa: ARG002
            return {"drain": drain, "remaining_depth": 0, "canceled_jobs": 0, "alive_workers": 0}

    queue = _StubQueue()
    calls: list[tuple[str, str]] = []

    def _factory(handler, settings, logger, source_label):  # noqa: ANN001
        calls.append((settings.async_sync_queue_db_path, source_label))
        return queue

    interactor = ParseAndSyncInteractor(
        repository=mock_lexicon_repository,
        category_repository=mock_category_repository,
        settings=ParseSyncSettings(
            auto_sync_enabled=True,
            enable_second_pass_wsd=False,
            enable_third_pass_llm=False,
            async_sync_enabled=True,
            async_sync_persistent_enabled=True,
            async_sync_queue_db_path="sync_queue.store",
        ),
        source_label="D:/worlds/infrastructure/persistence/data/lexicon-store",
        sync_queue_factory=_factory,
    )

    result = interactor.execute("Run fast", sync=True)

    assert result.success is True
    assert isinstance(result.data, ParseAndSyncResultDTO)
    assert result.data.summary["sync_async"] is True
    assert result.data.summary["sync_stage_status"]["reason"] == "async_sync_enabled_persistent"
    assert queue.enqueued >= 1
    assert len(calls) == 1
