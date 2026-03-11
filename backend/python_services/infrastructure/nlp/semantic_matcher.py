from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from difflib import SequenceMatcher
import numpy as np
from threading import RLock
import time
from typing import Any, List

from backend.python_services.core.domain import TokenRecord
from backend.python_services.infrastructure.config import PipelineSettings

from .index_provider import LexiconIndexSnapshot

# Compatibility aliases for tests that validate optional dependency fallbacks.
torch = None
AutoModel = None
AutoTokenizer = None

try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer

    _ST_IMPORT_ERROR: str | None = None
except Exception as _exc:
    _SentenceTransformer = None  # type: ignore[assignment,misc]
    _ST_IMPORT_ERROR = str(_exc)


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    open: bool
    failure_count: int
    open_until_epoch: float


class CircuitBreaker:
    def __init__(self, *, failures: int, reset_seconds: int) -> None:
        self._failures = max(1, failures)
        self._reset_seconds = max(1, reset_seconds)
        self._failure_count = 0
        self._open_until_epoch = 0.0
        self._lock = RLock()

    def allow(self) -> bool:
        with self._lock:
            now = time.time()
            if self._open_until_epoch and now < self._open_until_epoch:
                return False
            if self._open_until_epoch and now >= self._open_until_epoch:
                self._failure_count = 0
                self._open_until_epoch = 0.0
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._open_until_epoch = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self._failures:
                self._open_until_epoch = time.time() + self._reset_seconds

    def snapshot(self) -> CircuitBreakerSnapshot:
        with self._lock:
            now = time.time()
            return CircuitBreakerSnapshot(
                open=self._open_until_epoch > now,
                failure_count=self._failure_count,
                open_until_epoch=self._open_until_epoch,
            )


class SemanticMatcherStage:
    """Semantic similarity matcher.

    When ``bert_model_name`` is ``"string_similarity"`` (default), uses
    ``SequenceMatcher`` as a lightweight, deterministic fallback.

    When ``bert_model_name`` is set to a SentenceTransformer model name
    (e.g. ``"all-MiniLM-L6-v2"``), loads the model on first use and applies
    cosine similarity on real sentence embeddings for substantially better
    lexeme recognition across semantically related but orthographically
    different forms (e.g. *sprint* -> *run*).

    The model is loaded lazily in ``_try_load_model`` so that import time is
    not affected when a real model is not configured.

    Candidate embeddings are cached per lexicon version (``snapshot.version``)
    so that re-encoding the entire lexicon on every request is avoided.
    """

    def __init__(self, settings: PipelineSettings) -> None:
        self._settings = settings
        self._device = settings.bert_device
        self._model: Any | None = None
        self._st_import_error: str | None = _ST_IMPORT_ERROR
        self._unavailable_reason: str | None = None
        self._breaker = CircuitBreaker(
            failures=settings.bert_circuit_breaker_failures,
            reset_seconds=settings.bert_circuit_breaker_reset_seconds,
        )
        # LRU cache: lexicon version -> (candidate_forms_tuple, numpy_matrix)
        self._embedding_cache: OrderedDict[
            int, tuple[tuple[str, ...], Any]
        ] = OrderedDict()
        self._cache_lock = RLock()
        self._try_load_model()

    def _try_load_model(self) -> None:
        """Load a SentenceTransformer model when bert_model_name is set to a
        real model identifier. Falls back silently to string_similarity on any
        error so the pipeline always degrades gracefully."""
        name = self._settings.bert_model_name
        if not name or name == "string_similarity":
            return  # keep deterministic string_similarity behaviour (default)
        if _SentenceTransformer is None:
            self._unavailable_reason = (
                f"sentence_transformers unavailable: {self._st_import_error}"
            )
            return
        try:
            self._model = _SentenceTransformer(
                name,
                device=self._settings.bert_device,
                local_files_only=self._settings.bert_local_files_only,
            )
        except Exception as exc:
            self._unavailable_reason = str(exc)
            self._model = None

    @property
    def model_id(self) -> str:
        revision = self._settings.bert_model_revision or "default"
        return f"{self._settings.bert_model_name}@{revision}"

    def availability(self) -> dict[str, object]:
        breaker_state = self._breaker.snapshot()
        return {
            "bert_enabled": self._settings.enable_bert,
            "bert_available": True,
            "bert_unavailable_reason": self._unavailable_reason,
            "bert_model_name": self._settings.bert_model_name,
            "bert_model_revision": self._settings.bert_model_revision,
            "bert_threshold": self._settings.bert_threshold,
            "bert_device": self._device,
            "bert_onnx_enabled": self._settings.enable_bert_onnx,
            "bert_out_of_process_enabled": False,
            "bert_ipc_alive": False,
            "bert_circuit_open": breaker_state.open,
            "bert_circuit_failures": breaker_state.failure_count,
            "bert_circuit_open_until": breaker_state.open_until_epoch,
            "bert_backend": (
                "sentence_transformers" if self._model is not None else "string_similarity"
            ),
            "bert_model_loaded": self._model is not None,
        }

    def apply(
        self,
        tokens: list[TokenRecord],
        snapshot: LexiconIndexSnapshot,
    ) -> dict[str, object]:
        if self._model is not None:
            return self._apply_sbert(tokens, snapshot)
        return self._apply_string_similarity(tokens, snapshot)

    # ------------------------------------------------------------------
    # SBERT path
    # ------------------------------------------------------------------

    def _get_candidate_embeddings(
        self,
        candidate_forms: tuple[str, ...],
        version: int,
    ) -> tuple[tuple[str, ...], Any] | None:
        """Return *(forms, matrix)* for the given lexicon snapshot version.

        The embeddings matrix is cached so that the lexicon is only re-encoded
        when ``snapshot.version`` changes (i.e. after lexicon edits).
        Uses LRU eviction bounded by ``embedding_cache_max_entries``.
        """
        with self._cache_lock:
            if version in self._embedding_cache:
                self._embedding_cache.move_to_end(version)
                return self._embedding_cache[version]
            max_entries = max(1, self._settings.embedding_cache_max_entries)
            while len(self._embedding_cache) >= max_entries:
                self._embedding_cache.popitem(last=False)

        forms = list(candidate_forms[: self._settings.bert_top_k])
        if not forms:
            return None
        try:
            embeddings: Any = self._model.encode(  # type: ignore[union-attr]
                forms,
                batch_size=self._settings.bert_batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        except Exception as exc:
            self._breaker.record_failure()
            self._unavailable_reason = str(exc)
            return None

        result: tuple[tuple[str, ...], Any] = (tuple(forms), embeddings)
        with self._cache_lock:
            self._embedding_cache[version] = result
            self._embedding_cache.move_to_end(version)
        return result

    def _apply_sbert(
        self,
        tokens: list[TokenRecord],
        snapshot: LexiconIndexSnapshot,
    ) -> dict[str, object]:
        unknown_items = [
            (index, token) for index, token in enumerate(tokens) if not token.known
        ]
        unknown_count = len(unknown_items)
        if unknown_count == 0:
            return {"status": "ok", "reason": "", "unknown_tokens": 0, "matched_tokens": 0}
        if unknown_count > self._settings.max_unknown_tokens_for_bert:
            return {
                "status": "skipped",
                "reason": "max_unknown_tokens_exceeded",
                "unknown_tokens": unknown_count,
            }
        if not self._settings.enable_bert:
            return {
                "status": "skipped",
                "reason": "bert_disabled",
                "unknown_tokens": unknown_count,
            }
        if not self._breaker.allow():
            return {
                "status": "skipped",
                "reason": "bert_circuit_open",
                "unknown_tokens": unknown_count,
            }

        candidate_forms = tuple(sorted(snapshot.single_word.keys()))
        if not candidate_forms:
            return {
                "status": "skipped",
                "reason": "empty_lexicon",
                "unknown_tokens": unknown_count,
            }

        cached = self._get_candidate_embeddings(candidate_forms, snapshot.version)
        if cached is None:
            # Encoding failed; fall back gracefully to string similarity
            return self._apply_string_similarity(tokens, snapshot)
        forms_sub, candidate_embeddings = cached

        probes = [
            (token.lemma or token.normalized).strip().lower()
            for _, token in unknown_items
        ]
        try:
            query_embeddings: Any = self._model.encode(  # type: ignore[union-attr]
                probes,
                batch_size=self._settings.bert_batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        except Exception as exc:
            self._breaker.record_failure()
            self._unavailable_reason = str(exc)
            return self._apply_string_similarity(tokens, snapshot)

        # Dot product of L2-normalised vectors == cosine similarity
        similarities: Any = query_embeddings @ candidate_embeddings.T

        matched_tokens = 0
        for query_idx, (token_index, token) in enumerate(unknown_items):
            row = similarities[query_idx]
            best_idx = int(np.argmax(row))
            best_score = float(row[best_idx])
            if best_score < self._settings.bert_threshold:
                continue
            best_form = forms_sub[best_idx]
            token.categories = list(snapshot.single_word.get(best_form, ()))
            token.known = True
            token.match_source = "bert"
            token.matched_form = best_form
            token.bert_score = round(best_score, 4)
            tokens[token_index] = token
            matched_tokens += 1

        self._breaker.record_success()
        return {
            "status": "ok",
            "reason": "",
            "unknown_tokens": unknown_count,
            "matched_tokens": matched_tokens,
            "candidate_count": len(forms_sub),
            "cache_hit": False,
            "bert_mode": "sentence_transformers",
        }

    # ------------------------------------------------------------------
    # String-similarity path (original behaviour, preserved as fallback)
    # ------------------------------------------------------------------

    def _apply_string_similarity(
        self,
        tokens: list[TokenRecord],
        snapshot: LexiconIndexSnapshot,
    ) -> dict[str, object]:
        unknown_items = [(index, token) for index, token in enumerate(tokens) if not token.known]
        unknown_count = len(unknown_items)
        if unknown_count == 0:
            return {"status": "ok", "reason": "", "unknown_tokens": 0, "matched_tokens": 0}
        if unknown_count > self._settings.max_unknown_tokens_for_bert:
            return {
                "status": "skipped",
                "reason": "max_unknown_tokens_exceeded",
                "unknown_tokens": unknown_count,
            }
        if not self._settings.enable_bert:
            return {"status": "skipped", "reason": "bert_disabled", "unknown_tokens": unknown_count}
        if not self._breaker.allow():
            return {"status": "skipped", "reason": "bert_circuit_open", "unknown_tokens": unknown_count}

        candidate_forms = tuple(sorted(snapshot.single_word.keys()))
        if not candidate_forms:
            return {"status": "skipped", "reason": "empty_lexicon", "unknown_tokens": unknown_count}

        matched_tokens = 0
        for token_index, token in unknown_items:
            probe = (token.lemma or token.normalized).strip().lower()
            if not probe:
                continue
            best_form = ""
            best_score = 0.0
            for candidate in candidate_forms:
                score = self._cheap_similarity(probe, candidate)
                if score > best_score:
                    best_score = score
                    best_form = candidate
            if not best_form or best_score < self._settings.bert_threshold:
                continue
            token.categories = list(snapshot.single_word.get(best_form, ()))
            token.known = True
            token.match_source = "bert"
            token.matched_form = best_form
            token.bert_score = round(best_score, 4)
            tokens[token_index] = token
            matched_tokens += 1

        self._breaker.record_success()
        return {
            "status": "ok",
            "reason": "",
            "unknown_tokens": unknown_count,
            "matched_tokens": matched_tokens,
            "candidate_count": len(candidate_forms),
            "cache_hit": False,
            "bert_mode": "string_similarity",
        }

    def close(self) -> None:
        self._model = None
        with self._cache_lock:
            self._embedding_cache.clear()

    def _cheap_similarity(self, query: str, candidate: str) -> float:
        if not query or not candidate:
            return 0.0
        ratio = SequenceMatcher(a=query, b=candidate).ratio()
        bonus = 0.0
        if candidate.startswith(query[:2]):
            bonus += 0.15
        if query in candidate or candidate in query:
            bonus += 0.1
        length_delta = abs(len(candidate) - len(query))
        length_score = 1.0 - (length_delta / max(len(query), len(candidate), 1))
        bonus += 0.1 * max(0.0, length_score)
        return ratio + bonus

