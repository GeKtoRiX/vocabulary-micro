from __future__ import annotations

"""Unit tests for SemanticMatcherStage.

Covers:
- Default string_similarity path (bert_model_name="string_similarity")
- SBERT path: model loaded, apply dispatches correctly, bert_mode reported
- SBERT path: graceful fallback to string_similarity on encoding error
- SBERT path: embedding cache keyed on snapshot.version
- Circuit-breaker interaction
- close() clears model and cache
"""

from types import MappingProxyType
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from infrastructure.config import PipelineSettings
from infrastructure.sqlite.index_provider import LexiconIndexSnapshot
from core.domain import TokenRecord
from infrastructure.sqlite.phrase_matcher import PhraseTrieMatcher
from infrastructure.sqlite.semantic_matcher import SemanticMatcherStage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> PipelineSettings:
    defaults = dict(
        enable_bert=True,
        bert_model_name="string_similarity",
        bert_threshold=0.62,
        bert_top_k=400,
        bert_batch_size=64,
        bert_device="cpu",
        bert_local_files_only=True,
        bert_model_revision=None,
        max_unknown_tokens_for_bert=128,
        embedding_cache_max_entries=4,
        bert_circuit_breaker_failures=3,
        bert_circuit_breaker_reset_seconds=300,
        enable_bert_onnx=False,
    )
    defaults.update(overrides)
    return PipelineSettings(**defaults)


def _snapshot(words: dict[str, tuple[str, ...]], version: int = 1) -> LexiconIndexSnapshot:
    return LexiconIndexSnapshot(
        version=version,
        single_word=MappingProxyType(words),
        multi_word=MappingProxyType({}),
        phrase_matcher=PhraseTrieMatcher(),
        candidate_hash="test",
    )


def _token(normalized: str, lemma: str = "", known: bool = False) -> TokenRecord:
    return TokenRecord(
        token=normalized,
        normalized=normalized,
        lemma=lemma or normalized,
        pos="NOUN",
        start=0,
        end=len(normalized),
        known=known,
    )


def _mock_sbert_model(embeddings_map: dict[str, np.ndarray]) -> MagicMock:
    """Return a mock SentenceTransformer that returns deterministic embeddings."""
    model = MagicMock()

    def _encode(texts, **kwargs):
        rows = []
        for t in texts:
            vec = embeddings_map.get(t, np.zeros(4, dtype=np.float32))
            norm = np.linalg.norm(vec)
            rows.append(vec / norm if norm > 0 else vec)
        return np.array(rows, dtype=np.float32)

    model.encode.side_effect = _encode
    return model


# ---------------------------------------------------------------------------
# String-similarity path (default) - unchanged behaviour
# ---------------------------------------------------------------------------

class TestStringSimilarityPath:
    def test_apply_returns_string_similarity_mode(self):
        stage = SemanticMatcherStage(_settings())
        assert stage._model is None
        tokens = [_token("run")]
        result = stage.apply(tokens, _snapshot({"run": ("Verb",)}))
        assert result["bert_mode"] == "string_similarity"

    def test_apply_matches_exact_token(self):
        stage = SemanticMatcherStage(_settings())
        tokens = [_token("run")]
        stage.apply(tokens, _snapshot({"run": ("Verb",)}))
        assert tokens[0].known is True
        assert tokens[0].matched_form == "run"
        assert tokens[0].match_source == "bert"

    def test_apply_skips_known_tokens(self):
        stage = SemanticMatcherStage(_settings())
        tokens = [_token("run", known=True)]
        result = stage.apply(tokens, _snapshot({"run": ("Verb",)}))
        assert result["unknown_tokens"] == 0
        assert result["matched_tokens"] == 0

    def test_apply_respects_bert_disabled(self):
        stage = SemanticMatcherStage(_settings(enable_bert=False))
        tokens = [_token("run")]
        result = stage.apply(tokens, _snapshot({"run": ("Verb",)}))
        assert result["status"] == "skipped"
        assert result["reason"] == "bert_disabled"

    def test_availability_reports_string_similarity_backend(self):
        stage = SemanticMatcherStage(_settings())
        avail = stage.availability()
        assert avail["bert_backend"] == "string_similarity"
        assert avail["bert_model_loaded"] is False


# ---------------------------------------------------------------------------
# SBERT path - model loaded via _try_load_model
# ---------------------------------------------------------------------------

class TestSbertPath:
    def _make_stage_with_mock_model(self, model: MagicMock) -> SemanticMatcherStage:
        """Create stage with a pre-injected mock model (bypasses actual loading)."""
        stage = SemanticMatcherStage(_settings(bert_model_name="all-MiniLM-L6-v2"))
        stage._model = model  # inject after init to avoid real loading
        return stage

    def test_apply_dispatches_to_sbert_when_model_loaded(self):
        vecs = {
            "run": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            "sprint": np.array([0.99, 0.1, 0.0, 0.0], dtype=np.float32),
        }
        model = _mock_sbert_model(vecs)
        stage = self._make_stage_with_mock_model(model)
        tokens = [_token("sprint")]
        result = stage.apply(tokens, _snapshot({"run": ("Verb",)}))
        assert result["bert_mode"] == "sentence_transformers"
        assert tokens[0].known is True
        assert tokens[0].matched_form == "run"
        assert tokens[0].match_source == "bert"
        assert tokens[0].bert_score is not None
        assert tokens[0].bert_score >= 0.62

    def test_availability_reports_sentence_transformers_backend(self):
        model = MagicMock()
        stage = self._make_stage_with_mock_model(model)
        avail = stage.availability()
        assert avail["bert_backend"] == "sentence_transformers"
        assert avail["bert_model_loaded"] is True

    def test_sbert_below_threshold_not_matched(self):
        # Sprint is orthogonally far from "swim" -> low cosine
        vecs = {
            "sprint": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            "swim": np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
        }
        model = _mock_sbert_model(vecs)
        stage = self._make_stage_with_mock_model(model)
        stage._settings = _settings(bert_model_name="all-MiniLM-L6-v2", bert_threshold=0.99)
        tokens = [_token("sprint")]
        result = stage.apply(tokens, _snapshot({"swim": ("Verb",)}))
        assert tokens[0].known is False
        assert result["matched_tokens"] == 0

    def test_sbert_skips_known_tokens(self):
        model = MagicMock()
        stage = self._make_stage_with_mock_model(model)
        tokens = [_token("run", known=True)]
        result = stage.apply(tokens, _snapshot({"run": ("Verb",)}))
        assert result["unknown_tokens"] == 0
        model.encode.assert_not_called()

    def test_sbert_respects_bert_disabled(self):
        model = MagicMock()
        stage = self._make_stage_with_mock_model(model)
        stage._settings = _settings(
            bert_model_name="all-MiniLM-L6-v2",
            enable_bert=False,
        )
        tokens = [_token("run")]
        result = stage.apply(tokens, _snapshot({"run": ("Verb",)}))
        assert result["status"] == "skipped"
        assert result["reason"] == "bert_disabled"
        model.encode.assert_not_called()

    def test_sbert_fallback_on_encode_error(self):
        """If candidate encoding fails, stage falls back to string_similarity."""
        model = MagicMock()
        model.encode.side_effect = RuntimeError("CUDA OOM")
        stage = self._make_stage_with_mock_model(model)
        tokens = [_token("run")]
        result = stage.apply(tokens, _snapshot({"run": ("Verb",)}))
        # String similarity can still match "run" -> "run"
        assert result["status"] == "ok"
        assert tokens[0].known is True

    def test_sbert_cache_hit_does_not_re_encode_candidates(self):
        vecs = {
            "run": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            "sprint": np.array([0.99, 0.1, 0.0, 0.0], dtype=np.float32),
        }
        model = _mock_sbert_model(vecs)
        stage = self._make_stage_with_mock_model(model)
        snapshot = _snapshot({"run": ("Verb",)}, version=42)

        # First call - should encode candidates
        tokens1 = [_token("sprint")]
        stage.apply(tokens1, snapshot)
        first_call_count = model.encode.call_count

        # Second call with same snapshot version - candidates must not be re-encoded
        tokens2 = [_token("sprint")]
        stage.apply(tokens2, snapshot)
        # Only the query token was encoded again, not the full candidate list
        assert model.encode.call_count == first_call_count + 1

    def test_sbert_cache_invalidated_on_version_change(self):
        vecs = {
            "run": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            "sprint": np.array([0.99, 0.1, 0.0, 0.0], dtype=np.float32),
        }
        model = _mock_sbert_model(vecs)
        stage = self._make_stage_with_mock_model(model)

        snap_v1 = _snapshot({"run": ("Verb",)}, version=1)
        snap_v2 = _snapshot({"run": ("Verb",), "jog": ("Verb",)}, version=2)

        tokens1 = [_token("sprint")]
        stage.apply(tokens1, snap_v1)
        encode_after_v1 = model.encode.call_count

        tokens2 = [_token("sprint")]
        stage.apply(tokens2, snap_v2)
        # Candidate re-encoding must have happened (new version)
        assert model.encode.call_count > encode_after_v1 + 1


# ---------------------------------------------------------------------------
# _try_load_model - guards and error handling
# ---------------------------------------------------------------------------

class TestTryLoadModel:
    def test_no_model_loaded_for_string_similarity_default(self):
        stage = SemanticMatcherStage(_settings(bert_model_name="string_similarity"))
        assert stage._model is None

    def test_model_load_error_stored_as_unavailable_reason(self):
        with patch(
            "infrastructure.sqlite.semantic_matcher._SentenceTransformer",
            side_effect=OSError("model not found"),
        ):
            stage = SemanticMatcherStage(
                _settings(bert_model_name="all-MiniLM-L6-v2", bert_local_files_only=True)
            )
        assert stage._model is None
        assert "model not found" in (stage._unavailable_reason or "")

    def test_model_loaded_when_sentence_transformers_unavailable_falls_back(self):
        with patch(
            "infrastructure.sqlite.semantic_matcher._SentenceTransformer",
            None,
        ):
            stage = SemanticMatcherStage(
                _settings(bert_model_name="all-MiniLM-L6-v2")
            )
        assert stage._model is None
        # Should fall back to string_similarity seamlessly
        tokens = [_token("run")]
        result = stage.apply(tokens, _snapshot({"run": ("Verb",)}))
        assert result["bert_mode"] == "string_similarity"


# ---------------------------------------------------------------------------
# close() - cleanup
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_clears_model_and_cache(self):
        model = MagicMock()
        stage = SemanticMatcherStage(_settings(bert_model_name="all-MiniLM-L6-v2"))
        stage._model = model
        stage._embedding_cache[1] = (("run",), MagicMock())

        stage.close()

        assert stage._model is None
        assert len(stage._embedding_cache) == 0

