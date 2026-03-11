from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, replace
import time
import uuid
from typing import Dict, List, Tuple

from backend.python_services.core.domain import PipelineStats, StageStatus, TokenRecord
from backend.python_services.core.domain.services import POS_CATEGORY_HINTS
from backend.python_services.infrastructure.config import PipelineSettings
from backend.python_services.infrastructure.logging import get_logger, get_metrics_registry, get_tracer, log_event, start_span

from .exact_matcher import ExactMatcherStage
from .index_provider import LexiconIndexProvider, LexiconIndexSnapshot
from .lemma_inflect_matcher import LemmaInflectMatcherStage
from .table_models import LexiconEntry
from .semantic_matcher import SemanticMatcherStage
from .text_utils import NON_LATIN_SCRIPT_PATTERN, TOKEN_PATTERN, normalize_whitespace
from .tokenizer import TokenizerStage
from .wordnet_matcher import WordNetMatcherStage


class LexiconEngine:
    DEFAULT_BERT_MODEL = "string_similarity"
    DEFAULT_BERT_THRESHOLD = 0.62

    def __init__(
        self,
        language: str = "en",
        bert_model_name: str | None = None,
        bert_threshold: float = DEFAULT_BERT_THRESHOLD,
        settings: PipelineSettings | None = None,
    ) -> None:
        if language.lower() != "en":
            raise ValueError("Only English language is supported by this pipeline.")

        base_settings = settings or PipelineSettings.from_env()
        self.settings = replace(
            base_settings,
            bert_model_name=bert_model_name or base_settings.bert_model_name,
            bert_threshold=bert_threshold,
        )
        self.language = "en"
        self.bert_model_name = self.settings.bert_model_name
        self.bert_threshold = self.settings.bert_threshold

        self._index_provider: LexiconIndexProvider | None = None
        self._tokenizer = TokenizerStage(self.settings)
        self._exact = ExactMatcherStage()
        self._lemma = LemmaInflectMatcherStage(self.settings)
        self._wordnet = WordNetMatcherStage(self.settings)
        self._semantic = SemanticMatcherStage(self.settings)

        self._logger = get_logger("lexicon_engine")
        self._metrics = get_metrics_registry()
        self._tracer = get_tracer("lexicon_engine")

    def bind_index_provider(self, provider: LexiconIndexProvider) -> None:
        self._index_provider = provider

    def iter_entries(self) -> List[LexiconEntry]:
        raise NotImplementedError

    def get_lexicon_version(self) -> int:
        return 0

    def _is_english_text(self, text: str) -> bool:
        return NON_LATIN_SCRIPT_PATTERN.search(text) is None

    def _build_snapshot_from_entries(self) -> tuple[LexiconIndexSnapshot, bool]:
        if self._index_provider is not None:
            snapshot, cache_hit = self._index_provider.get_snapshot()
            return snapshot, cache_hit
        single_word: Dict[str, set[str]] = defaultdict(set)
        multi_word: Dict[Tuple[str, ...], set[str]] = defaultdict(set)
        for entry in self.iter_entries():
            pieces = [token.lower() for token in TOKEN_PATTERN.findall(entry.value)]
            if not pieces:
                continue
            if len(pieces) == 1:
                single_word[pieces[0]].add(entry.category)
            else:
                multi_word[tuple(pieces)].add(entry.category)
        from .index_provider import LexiconIndexProvider

        provider = LexiconIndexProvider(entry_loader=self.iter_entries, version_loader=self.get_lexicon_version)
        return provider.snapshot_from_maps(single_word, multi_word, self.get_lexicon_version()), False

    def build_index(self) -> Tuple[Dict[str, List[str]], Dict[Tuple[str, ...], List[str]]]:
        snapshot, _ = self._build_snapshot_from_entries()
        return snapshot.as_legacy()

    def pipeline_status(self) -> Dict[str, object]:
        return {
            "language": self.language,
            "spacy_available": self._tokenizer.spacy_available,
            "spacy_import_error": self._tokenizer.spacy_import_error,
            "lemminflect_available": self._lemma.available,
            "wordnet_enabled": self.settings.enable_wordnet,
            "wordnet_available": self._wordnet.available,
            "wordnet_unavailable_reason": self._wordnet.unavailable_reason,

            "omw_available": self._wordnet.omw_available,

            "omw_unavailable_reason": self._wordnet.omw_unavailable_reason,

            **self._semantic.availability(),
            "lexicon_version": self.get_lexicon_version(),
            "config": {
                "enable_bert": self.settings.enable_bert,
                "enable_lemminflect": self.settings.enable_lemminflect,
                "enable_wordnet": self.settings.enable_wordnet,
                "max_input_chars": self.settings.max_input_chars,
                "max_input_tokens": self.settings.max_input_tokens,
                "max_request_bytes": self.settings.max_request_bytes,
                "request_timeout_ms": self.settings.request_timeout_ms,
                "tokenize_timeout_ms": self.settings.tokenize_timeout_ms,
                "exact_match_timeout_ms": self.settings.exact_match_timeout_ms,
                "lemma_timeout_ms": self.settings.lemma_timeout_ms,
                "wordnet_timeout_ms": self.settings.wordnet_timeout_ms,
                "bert_timeout_ms": self.settings.bert_timeout_ms,
                "max_inflect_candidates_per_token": self.settings.max_inflect_candidates_per_token,
                "max_unknown_tokens_for_lemma_stage": self.settings.max_unknown_tokens_for_lemma_stage,
                "max_unknown_tokens_for_wordnet": self.settings.max_unknown_tokens_for_wordnet,
                "max_unknown_tokens_for_bert": self.settings.max_unknown_tokens_for_bert,
                "bert_top_k": self.settings.bert_top_k,
                "max_bert_candidates": self.settings.max_bert_candidates,
                "api_queue_max_size": self.settings.api_queue_max_size,
                "api_reject_status_code": self.settings.api_reject_status_code,
                "async_sync_enabled": self.settings.async_sync_enabled,
                "async_sync_persistent_enabled": self.settings.async_sync_persistent_enabled,
                "async_sync_queue_size": self.settings.async_sync_queue_size,
                "async_sync_worker_count": self.settings.async_sync_worker_count,
                "async_sync_queue_path": self.settings.async_sync_queue_db_path,
                "bert_out_of_process_enabled": self.settings.bert_out_of_process_enabled,
                "bert_ipc_host": self.settings.bert_ipc_host,
                "bert_ipc_port": self.settings.bert_ipc_port,
                "index_rebuild_debounce_seconds": self.settings.index_rebuild_debounce_seconds,
                "bert_local_files_only": self.settings.bert_local_files_only,
                "enable_second_pass_wsd": self.settings.enable_second_pass_wsd,
                "second_pass_top_n": self.settings.second_pass_top_n,
                "second_pass_similarity_threshold": self.settings.second_pass_similarity_threshold,
                "second_pass_margin_threshold": self.settings.second_pass_margin_threshold,
                "second_pass_max_gap_tokens": self.settings.second_pass_max_gap_tokens,
                "spacy_trf_model_name": self.settings.spacy_trf_model_name,
                "st_model_name": self.settings.st_model_name,
                "st_model_revision": self.settings.st_model_revision,
                "st_local_files_only": self.settings.st_local_files_only,
                "st_batch_size": self.settings.st_batch_size,
                "enable_third_pass_llm": self.settings.enable_third_pass_llm,
                "third_pass_llm_base_url": self.settings.third_pass_llm_base_url,
                "third_pass_llm_model": self.settings.third_pass_llm_model,
                "third_pass_llm_timeout_ms": self.settings.third_pass_llm_timeout_ms,
                "third_pass_llm_max_tokens": self.settings.third_pass_llm_max_tokens,
                "third_pass_llm_max_items": self.settings.third_pass_llm_max_items,
            },
        }

    def parse_text(self, text: str, request_id: str | None = None) -> Dict[str, object]:
        request_id = request_id or uuid.uuid4().hex
        request_start = time.perf_counter()
        stage_statuses: list[StageStatus] = []

        if not self._is_english_text(text):
            return self._error_response(
                request_id=request_id,
                message="Only English text is supported by this pipeline.",
                stage_statuses=stage_statuses,
            )
        if len(text) > self.settings.max_input_chars:
            return self._error_response(
                request_id=request_id,
                message=f"Input exceeds MAX_INPUT_CHARS ({self.settings.max_input_chars}).",
                stage_statuses=stage_statuses,
            )
        request_bytes = len(text.encode("utf-8"))
        if request_bytes > self.settings.max_request_bytes:
            return self._error_response(
                request_id=request_id,
                message=f"Input exceeds MAX_REQUEST_BYTES ({self.settings.max_request_bytes}).",
                stage_statuses=stage_statuses,
            )

        with start_span(self._tracer, "request_intake"):
            snapshot, snapshot_cache_hit = self._build_snapshot_from_entries()

        deadline = time.monotonic() + (self.settings.request_timeout_ms / 1000.0)
        tokens: list[TokenRecord] = []
        phrase_matches = []
        tokenize_doc = None
        pop_tokenize_doc = getattr(self._tokenizer, "pop_last_doc", None)

        pop_tokenize_backend = getattr(self._tokenizer, "pop_last_backend", None)

        if callable(pop_tokenize_doc):

            try:

                pop_tokenize_doc()

            except Exception:

                pass

        if callable(pop_tokenize_backend):

            try:

                pop_tokenize_backend()

            except Exception:

                pass

        tokenize_status = self._run_stage(
            stage="tokenize",
            timeout_ms=self.settings.tokenize_timeout_ms,
            deadline=deadline,
            execute=lambda: self._tokenizer.tokenize(text),
            on_result=lambda payload: self._tokenize_on_result(payload, tokens),
        )
        stage_statuses.append(tokenize_status)
        if callable(pop_tokenize_doc):
            try:
                tokenize_doc = pop_tokenize_doc()
            except Exception:
                tokenize_doc = None

        if self._is_blocking_stage(tokenize_status):
            stage_statuses.append(
                self._skipped_stage_status(
                    stage="exact_match",
                    reason="tokenize_stage_not_ok",
                )
            )
            stage_statuses.append(
                self._skipped_stage_status(
                    stage="lemma_inflect",
                    reason="tokenize_stage_not_ok",
                )
            )
            stage_statuses.append(
                self._skipped_stage_status(
                    stage="wordnet_match",
                    reason="tokenize_stage_not_ok",
                )
            )
            stage_statuses.append(
                self._skipped_stage_status(
                    stage="bert_match",
                    reason="tokenize_stage_not_ok",
                )
            )
        else:
            exact_status = self._run_stage(
                stage="exact_match",
                timeout_ms=self.settings.exact_match_timeout_ms,
                deadline=deadline,
                execute=lambda: self._run_exact_stage(text=text, tokens=tokens, snapshot=snapshot),
                on_result=lambda payload: phrase_matches.extend(payload),
            )
            stage_statuses.append(exact_status)

            if self._is_blocking_stage(exact_status):
                stage_statuses.append(
                    self._skipped_stage_status(
                        stage="lemma_inflect",
                        reason="exact_stage_not_ok",
                    )
                )
                stage_statuses.append(
                    self._skipped_stage_status(
                        stage="wordnet_match",
                        reason="exact_stage_not_ok",
                    )
                )
                stage_statuses.append(
                    self._skipped_stage_status(
                        stage="bert_match",
                        reason="exact_stage_not_ok",
                    )
                )
            else:
                lemma_status = self._run_stage(
                    stage="lemma_inflect",
                    timeout_ms=self.settings.lemma_timeout_ms,
                    deadline=deadline,
                    execute=lambda: self._lemma.apply(tokens, dict(snapshot.single_word)),
                )
                stage_statuses.append(lemma_status)

                if self._is_blocking_stage(lemma_status):
                    stage_statuses.append(
                        self._skipped_stage_status(
                            stage="wordnet_match",
                            reason="lemma_stage_not_ok",
                        )
                    )
                    stage_statuses.append(
                        self._skipped_stage_status(
                            stage="bert_match",
                            reason="lemma_stage_not_ok",
                        )
                    )
                else:
                    wordnet_status = self._run_stage(
                        stage="wordnet_match",
                        timeout_ms=self.settings.wordnet_timeout_ms,
                        deadline=deadline,
                        execute=lambda: self._wordnet.apply(tokens),
                    )
                    stage_statuses.append(wordnet_status)

                    if self._is_blocking_stage(wordnet_status):
                        stage_statuses.append(
                            self._skipped_stage_status(
                                stage="bert_match",
                                reason="wordnet_stage_not_ok",
                            )
                        )
                    else:
                        stage_statuses.append(
                            self._run_stage(
                                stage="bert_match",
                                timeout_ms=self.settings.bert_timeout_ms,
                                deadline=deadline,
                                execute=lambda: self._semantic.apply(tokens, snapshot),
                            )
                        )

        self._apply_pos_category_hints(tokens)
        if (
            tokenize_doc is not None
            and tokenize_status.status == "ok"
            and not bool(tokenize_status.metadata.get("truncated", False))
        ):
            self._cache_request_doc(request_id=request_id, text=text, doc=tokenize_doc)

        stats = self._build_stats(tokens)
        response = {
            "tokens": [item.to_dict() for item in tokens],
            "phrase_matches": [item.to_dict() for item in phrase_matches],
            "stats": stats.to_dict(),
            "pipeline": self.pipeline_status(),
            "stage_statuses": [item.to_dict() for item in stage_statuses],
            "request_id": request_id,
            "pipeline_status": self._derive_pipeline_status(stage_statuses),
            "lexicon_version": snapshot.version,
        }

        duration_ms = (time.perf_counter() - request_start) * 1000.0
        self._metrics.inc("lexicon.requests.total")
        self._metrics.observe("lexicon.requests.duration_ms", duration_ms)
        stage_duration_map = {item.stage: item.duration_ms for item in stage_statuses}
        self._metrics.observe("lexicon.stage.tokenize.duration_ms", stage_duration_map.get("tokenize", 0.0))
        self._metrics.observe("lexicon.stage.exact.duration_ms", stage_duration_map.get("exact_match", 0.0))
        self._metrics.observe("lexicon.stage.lemma.duration_ms", stage_duration_map.get("lemma_inflect", 0.0))
        self._metrics.observe("lexicon.stage.wordnet.duration_ms", stage_duration_map.get("wordnet_match", 0.0))
        self._metrics.observe("lexicon.stage.bert.duration_ms", stage_duration_map.get("bert_match", 0.0))
        if snapshot_cache_hit:
            self._metrics.inc("lexicon.index.cache_hit")
        else:
            self._metrics.inc("lexicon.index.cache_miss")

        log_event(
            self._logger,
            event="lexicon_request_completed",
            request_id=request_id,
            duration_ms=round(duration_ms, 3),
            lexicon_version=snapshot.version,
            unknown_count=stats.unknown_tokens,
            cache_hit=snapshot_cache_hit,
            pipeline_status=response["pipeline_status"],
        )
        return response

    def _run_exact_stage(
        self,
        *,
        text: str,
        tokens: list[TokenRecord],
        snapshot: LexiconIndexSnapshot,
    ):
        self._exact.apply_token_matching(tokens=tokens, snapshot=snapshot)
        return self._exact.apply_phrase_matching(text=text, tokens=tokens, snapshot=snapshot)

    def _tokenize_on_result(
        self,
        payload,
        tokens: list[TokenRecord],
        *,
        set_doc=None,
    ) -> dict[str, object]:
        stage_tokens = []
        truncated = False
        doc = None
        if isinstance(payload, tuple):
            if len(payload) >= 2:
                stage_tokens = payload[0]
                truncated = bool(payload[1])
            if len(payload) >= 3:
                doc = payload[2]
        else:
            stage_tokens = payload
        tokens.extend(stage_tokens)
        if callable(set_doc):
            set_doc(doc)
        return {

            "token_count": len(stage_tokens),

            "truncated": truncated,

            "tokenizer_backend": str(getattr(self._tokenizer, "last_backend", "unknown")),

        }

    def _is_blocking_stage(self, status: StageStatus) -> bool:
        return status.status in {"failed", "timed_out"}

    def _skipped_stage_status(self, *, stage: str, reason: str) -> StageStatus:
        return StageStatus(
            stage=stage,
            status="skipped",
            duration_ms=0.0,
            reason=reason,
        )

    def _cache_request_doc(self, *, request_id: str, text: str, doc: object) -> None:
        del request_id, text, doc
        return None

    def _run_stage(
        self,
        *,
        stage: str,
        timeout_ms: int,
        deadline: float,
        execute,
        on_result=None,
    ) -> StageStatus:
        if time.monotonic() > deadline:
            return StageStatus(
                stage=stage,
                status="skipped",
                duration_ms=0.0,
                reason="request_deadline_exceeded",
            )
        start = time.perf_counter()
        try:
            with start_span(self._tracer, stage):
                result = execute()
            metadata = {}
            if on_result is not None:
                on_result_payload = on_result(result)
                if isinstance(on_result_payload, dict):
                    metadata.update(on_result_payload)
            if isinstance(result, dict):
                metadata.update(result)
            duration_ms = (time.perf_counter() - start) * 1000.0
            if duration_ms > timeout_ms:
                return StageStatus(
                    stage=stage,
                    status="timed_out",
                    duration_ms=duration_ms,
                    reason="stage_timeout_exceeded",
                    metadata=metadata,
                )
            return StageStatus(
                stage=stage,
                status=metadata.get("status", "ok"),
                duration_ms=duration_ms,
                reason=str(metadata.get("reason", "")),
                metadata=metadata,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._metrics.inc(f"lexicon.stage.{stage}.errors")
            log_event(
                self._logger,
                level=40,
                event="lexicon_stage_failed",
                stage=stage,
                duration_ms=round(duration_ms, 3),
                error_code="stage_exception",
                error=str(exc),
            )
            return StageStatus(
                stage=stage,
                status="failed",
                duration_ms=duration_ms,
                reason="stage_exception",
                metadata={"error": str(exc)},
            )

    def _build_stats(self, tokens: list[TokenRecord]) -> PipelineStats:
        known_tokens = sum(1 for item in tokens if item.known)
        total_tokens = len(tokens)
        coverage = 0.0
        if total_tokens:
            coverage = round((known_tokens / total_tokens) * 100, 2)

        source_counts: Dict[str, int] = defaultdict(int)
        for token_info in tokens:
            source_counts[token_info.match_source] += 1
        return PipelineStats(
            tokens_total=total_tokens,
            known_tokens=known_tokens,
            unknown_tokens=total_tokens - known_tokens,
            coverage_percent=coverage,
            source_counts=dict(source_counts),
        )

    def _derive_pipeline_status(self, statuses: list[StageStatus]) -> str:
        if any(item.status == "failed" for item in statuses):
            return "failed"
        if any(item.status in {"timed_out", "skipped"} for item in statuses):
            return "partial"
        return "ok"

    def _error_response(
        self,
        *,
        request_id: str,
        message: str,
        stage_statuses: list[StageStatus],
    ) -> Dict[str, object]:
        return {
            "error": message,
            "tokens": [],
            "phrase_matches": [],
            "stats": {
                "tokens_total": 0,
                "known_tokens": 0,
                "unknown_tokens": 0,
                "coverage_percent": 0.0,
                "source_counts": {},
            },
            "pipeline": self.pipeline_status(),
            "stage_statuses": [asdict(item) for item in stage_statuses],
            "pipeline_status": "failed",
            "request_id": request_id,
            "lexicon_version": self.get_lexicon_version(),
        }

    def close(self) -> None:
        self._semantic.close()

    def _apply_pos_category_hints(self, tokens: list[TokenRecord]) -> None:
        for token in tokens:
            pos_tag = (token.pos or "").strip().upper()
            hinted_category = POS_CATEGORY_HINTS.get(pos_tag)
            if token.categories:
                if hinted_category is None:
                    continue
                hinted_casefold = hinted_category.casefold()
                matched_category = next(
                    (
                        category
                        for category in token.categories
                        if str(category).strip().casefold() == hinted_casefold
                    ),
                    None,
                )
                if matched_category is None:
                    continue
                token.categories = [matched_category] + [
                    category
                    for category in token.categories
                    if str(category).strip().casefold() != hinted_casefold
                ]
                continue
            if hinted_category is None:
                continue
            token.categories = [hinted_category]
            if token.match_source == "none":
                token.match_source = "spacy_pos_hint"


__all__ = ["LexiconEngine", "LexiconEntry", "normalize_whitespace"]

