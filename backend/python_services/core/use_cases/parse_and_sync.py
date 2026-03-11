from __future__ import annotations

from typing import Any
import uuid

from backend.python_services.core.domain import ParseAndSyncResultDTO, ParseRowSyncResultDTO, Result
from backend.python_services.core.domain import (
    ICategoryRepository,
    ILexiconRepository,
    ILoggingService,
    ParseSyncSettings,
)
import backend.python_services.core.domain.reason_codes as domain_reasons
from backend.python_services.core.domain.services import ISyncQueue, TextProcessor
from backend.python_services.core.use_cases._base import BaseInteractor
from backend.python_services.core.use_cases.async_sync_queue_builder import AsyncSyncQueueBuilder, SyncQueueFactory
from backend.python_services.core.use_cases.parse_sync_candidate_resolver import SyncCandidateResolver
from backend.python_services.core.use_cases.parse_table_builder import ParseTableBuilder
from backend.python_services.core.use_cases.third_pass_orchestrator import ThirdPassOrchestrator

SUMMARY_SCHEMA_VERSION = 1
SECOND_PASS_SCHEMA_VERSION = 1


class ParseAndSyncInteractor(BaseInteractor):
    def __init__(
        self,
        repository: ILexiconRepository,
        category_repository: ICategoryRepository,
        auto_add_category: str = "Auto Added",
        settings: ParseSyncSettings | None = None,
        logger: ILoggingService | None = None,
        source_label: str = "lexicon",
        sync_queue_factory: SyncQueueFactory | None = None,
        text_processor: TextProcessor | None = None,
    ) -> None:
        self.parser = repository
        self.repository = repository
        self.category_repository = category_repository
        self._logger = logger
        self._text_processor = text_processor or TextProcessor()
        resolved_source_label = str(source_label).strip()
        self.lexicon_label = resolved_source_label or "lexicon"
        self.auto_add_category = str(auto_add_category or "").strip() or "Auto Added"
        self.settings = settings or ParseSyncSettings()

        self._candidate_resolver = SyncCandidateResolver(
            repository=repository,
            category_repository=category_repository,
            settings=self.settings,
            auto_add_category=self.auto_add_category,
            text_processor=self._text_processor,
            persistent_queue_enabled=bool(
                self.settings.async_sync_persistent_enabled and sync_queue_factory is not None
            ),
            log_error=lambda operation, error: self._log_error(operation=operation, error=error),
        )
        self._third_pass_orchestrator = ThirdPassOrchestrator(
            repository=repository,
            settings=self.settings,
            text_processor=self._text_processor,
            auto_add_category=self.auto_add_category,
            log_error=lambda operation, error: self._log_error(operation=operation, error=error),
        )
        self._table_builder = ParseTableBuilder(text_processor=self._text_processor)

        self._async_queue: ISyncQueue | None = None
        if self.settings.async_sync_enabled:
            queue_builder = AsyncSyncQueueBuilder(
                settings=self.settings,
                logger=logger,
                source_label=self.lexicon_label,
                sync_queue_factory=sync_queue_factory,
            )
            self._async_queue = queue_builder.build(
                handler=self._candidate_resolver.process_async_sync_job,
                log_info=self._log_info,
            )

    def execute(
        self,
        text: str,
        *,
        sync: bool | None = None,
        request_id: str | None = None,
        think_mode: bool | None = None,
        second_pass_wsd: bool | None = None,
        second_pass_top_n: int = 3,
        third_pass_think_mode: bool | None = None,
        third_pass_enabled: bool | None = None,
        third_pass_timeout_ms: int | None = None,
    ) -> Result[ParseAndSyncResultDTO]:
        request_id = request_id or uuid.uuid4().hex
        pipeline_build = self.settings.pipeline_build
        should_sync = self.settings.auto_sync_enabled if sync is None else sync
        effective_think_mode = third_pass_think_mode if third_pass_think_mode is not None else think_mode
        should_run_second_pass = (
            self.settings.enable_second_pass_wsd
            if second_pass_wsd is None
            else bool(second_pass_wsd)
        )
        should_run_third_pass = (
            bool(self.settings.enable_third_pass_llm)
            if third_pass_enabled is None
            else bool(third_pass_enabled)
        )

        if not text or not text.strip():
            sync_message = self._text_processor.format_sync_message([], [])
            self._release_request_resources(request_id=request_id)
            return Result.fail(
                "Enter English text for parsing.",
                status_code="empty_text",
                data=ParseAndSyncResultDTO(
                    table=[],
                    summary={
                        "schema_version": SUMMARY_SCHEMA_VERSION,
                        "pipeline_build": pipeline_build,
                        "error": "Enter English text for parsing.",
                        "sync_message": sync_message,
                        "request_id": request_id,
                        "sync_enabled": should_sync,
                        "second_pass": self._default_second_pass_summary(
                            enabled=should_run_second_pass,
                            reason=domain_reasons.REASON_EMPTY_TEXT,
                        ),
                        "third_pass": self._third_pass_orchestrator.default_summary(
                            enabled=should_run_third_pass,
                            reason=domain_reasons.REASON_EMPTY_TEXT,
                        ),
                    },
                    status_message="Enter English text for parsing.",
                    error_message="Enter English text for parsing.",
                ),
            )

        parsed = self._parse_with_request_id(text=text, request_id=request_id)
        if "error" in parsed:
            sync_message = self._text_processor.format_sync_message([], [])
            message = str(parsed.get("error", "Parse failed")).strip()
            summary = {
                "schema_version": SUMMARY_SCHEMA_VERSION,
                "pipeline_build": pipeline_build,
                "error": message,
                "pipeline": parsed.get("pipeline", self.parser.pipeline_status()),
                "stage_statuses": parsed.get("stage_statuses", []),
                "pipeline_status": parsed.get("pipeline_status", "failed"),
                "sync_message": sync_message,
                "added": [],
                "already_existed": [],
                "request_id": request_id,
                "sync_enabled": should_sync,
                "second_pass": self._default_second_pass_summary(
                    enabled=should_run_second_pass,
                    reason=domain_reasons.REASON_PARSE_ERROR,
                ),
                "third_pass": self._third_pass_orchestrator.default_summary(
                    enabled=should_run_third_pass,
                    reason=domain_reasons.REASON_PARSE_ERROR,
                ),
            }
            self._release_request_resources(request_id=request_id)
            return Result.fail(
                message,
                status_code="parse_failed",
                data=ParseAndSyncResultDTO(
                    table=[],
                    summary=summary,
                    status_message=f"Parse failed: {message}",
                    error_message=message,
                ),
            )

        direct_sync_enabled = should_sync and not (
            self.settings.async_sync_enabled and self._async_queue is not None
        )
        sync_existing_single: set[str] | None = None
        sync_existing_multi: set[str] | None = None
        sync_existing_categories: set[str] | None = None
        known_terms: set[str] = set()

        if direct_sync_enabled:
            (
                known_lemmas,
                sync_existing_single,
                sync_existing_multi,
                sync_existing_categories,
            ) = self._candidate_resolver.load_sync_index_state()
            known_terms.update(sync_existing_single or set())
            known_terms.update(sync_existing_multi or set())
        else:
            known_lemmas, known_terms = self._candidate_resolver.load_known_terms_from_repository()

        lexemes = self._text_processor.extract_lexemes(parsed["tokens"])
        phrasal_verbs = self._text_processor.extract_phrasal_verbs(parsed["tokens"])
        candidates = self._text_processor.unique(lexemes + phrasal_verbs)
        candidate_categories = self._candidate_resolver.build_candidate_categories(parsed["tokens"], phrasal_verbs)
        candidate_categories = self._candidate_resolver.canonicalize_candidate_categories(candidate_categories)
        accepted_candidates, rejected = self._candidate_resolver.partition_sync_candidates(
            candidates,
            candidate_categories=candidate_categories,
        )

        added: list[str] = []
        already_existed: list[str] = []
        queued_for_sync: list[str] = []
        category_review_required: list[dict[str, str]] = []

        sync_stage_status = {
            "status": "skipped",
            "reason": domain_reasons.REASON_SYNC_DISABLED,
            "duration_ms": 0.0,
        }
        sync_async = False
        if should_sync:
            if self.settings.async_sync_enabled and self._async_queue is not None:
                sync_async = True
                queued_for_sync, sync_stage_status = self._candidate_resolver.enqueue_async_sync(
                    accepted_candidates,
                    request_id=request_id,
                    candidate_categories=candidate_categories,
                    async_queue=self._async_queue,
                )
            else:
                added, already_existed, sync_stage_status, category_review_required = (
                    self._candidate_resolver.sync_candidates(
                        accepted_candidates,
                        request_id=request_id,
                        candidate_categories=candidate_categories,
                        existing_single=sync_existing_single,
                        existing_multi=sync_existing_multi,
                        existing_categories=sync_existing_categories,
                    )
                )

        second_pass_summary = self._default_second_pass_summary(
            enabled=False,
            reason=domain_reasons.REASON_NOT_REQUESTED,
        )
        if should_run_second_pass:
            second_pass_summary = self._run_second_pass(
                text=text,
                request_id=request_id,
                top_n=max(1, int(second_pass_top_n)),
            )

            if should_sync:
                (
                    second_pass_candidates,
                    second_pass_candidate_categories,
                ) = self._third_pass_orchestrator.extract_second_pass_sync_candidates(second_pass_summary)
                second_pass_candidate_categories = self._candidate_resolver.canonicalize_candidate_categories(
                    second_pass_candidate_categories
                )
                second_pass_accepted, second_pass_rejected = self._candidate_resolver.partition_sync_candidates(
                    second_pass_candidates,
                    candidate_categories=second_pass_candidate_categories,
                )
                second_pass_added: list[str] = []
                second_pass_already_existed: list[str] = []
                second_pass_queued: list[str] = []
                second_pass_category_review_required: list[dict[str, str]] = []
                second_pass_sync_stage_status = {
                    "status": "ok",
                    "reason": domain_reasons.REASON_NO_CANDIDATES,
                    "duration_ms": 0.0,
                    "candidate_count": 0,
                }

                if second_pass_accepted:
                    if self.settings.async_sync_enabled and self._async_queue is not None:
                        sync_async = True
                        second_pass_queued, second_pass_sync_stage_status = self._candidate_resolver.enqueue_async_sync(
                            second_pass_accepted,
                            request_id=request_id,
                            candidate_categories=second_pass_candidate_categories,
                            async_queue=self._async_queue,
                        )
                        queued_for_sync.extend(second_pass_queued)
                    else:
                        (
                            second_pass_added,
                            second_pass_already_existed,
                            second_pass_sync_stage_status,
                            second_pass_category_review_required,
                        ) = self._candidate_resolver.sync_candidates(
                            second_pass_accepted,
                            request_id=request_id,
                            candidate_categories=second_pass_candidate_categories,
                            existing_single=sync_existing_single,
                            existing_multi=sync_existing_multi,
                            existing_categories=sync_existing_categories,
                        )
                        added.extend(second_pass_added)
                        already_existed.extend(second_pass_already_existed)
                        category_review_required.extend(second_pass_category_review_required)

                if second_pass_rejected:
                    rejected.extend(second_pass_rejected)

                second_pass_summary["sync_enabled"] = True
                second_pass_summary["sync_stage_status"] = second_pass_sync_stage_status
                second_pass_summary["added"] = second_pass_added
                second_pass_summary["already_existed"] = second_pass_already_existed
                second_pass_summary["queued_for_sync"] = second_pass_queued
                second_pass_summary["rejected_candidates"] = second_pass_rejected
                second_pass_summary["category_review_required"] = second_pass_category_review_required
            else:
                second_pass_summary["sync_enabled"] = False
                second_pass_summary["sync_stage_status"] = {
                    "status": "skipped",
                    "reason": domain_reasons.REASON_SYNC_DISABLED,
                    "duration_ms": 0.0,
                }

        third_pass_summary = self._third_pass_orchestrator.default_summary(
            enabled=False,
            reason=domain_reasons.REASON_NOT_REQUESTED,
        )
        third_pass_policy = self._third_pass_orchestrator.evaluate_validation_policy(
            third_pass_requested=bool(should_run_third_pass),
            second_pass_requested=bool(should_run_second_pass),
            second_pass_summary=second_pass_summary,
        )
        if should_run_third_pass and bool(third_pass_policy.get("allowed", False)):
            third_pass_summary = self._third_pass_orchestrator.run(
                text=text,
                request_id=request_id,
                think_mode=effective_think_mode,
                enabled=should_run_third_pass,
                timeout_ms=third_pass_timeout_ms,
            )
            (
                third_pass_candidates,
                third_pass_candidate_categories,
            ) = self._third_pass_orchestrator.extract_occurrence_sync_candidates(third_pass_summary)
            third_pass_candidate_categories = self._candidate_resolver.canonicalize_candidate_categories(
                third_pass_candidate_categories
            )
            third_pass_accepted, third_pass_rejected = self._candidate_resolver.partition_sync_candidates(
                third_pass_candidates,
                candidate_categories=third_pass_candidate_categories,
            )

            third_pass_added: list[str] = []
            third_pass_already_existed: list[str] = []
            third_pass_queued: list[str] = []
            third_pass_category_review_required: list[dict[str, str]] = []
            third_pass_sync_stage_status = {
                "status": "skipped",
                "reason": domain_reasons.REASON_SYNC_DISABLED,
                "duration_ms": 0.0,
                "candidate_count": len(third_pass_accepted),
            }

            if should_sync:
                if third_pass_accepted:
                    if self.settings.async_sync_enabled and self._async_queue is not None:
                        sync_async = True
                        third_pass_queued, third_pass_sync_stage_status = self._candidate_resolver.enqueue_async_sync(
                            third_pass_accepted,
                            request_id=request_id,
                            candidate_categories=third_pass_candidate_categories,
                            async_queue=self._async_queue,
                        )
                        queued_for_sync.extend(third_pass_queued)
                    else:
                        (
                            third_pass_added,
                            third_pass_already_existed,
                            third_pass_sync_stage_status,
                            third_pass_category_review_required,
                        ) = self._candidate_resolver.sync_candidates(
                            third_pass_accepted,
                            request_id=request_id,
                            candidate_categories=third_pass_candidate_categories,
                            existing_single=sync_existing_single,
                            existing_multi=sync_existing_multi,
                            existing_categories=sync_existing_categories,
                        )
                        added.extend(third_pass_added)
                        already_existed.extend(third_pass_already_existed)
                        category_review_required.extend(third_pass_category_review_required)
                else:
                    third_pass_sync_stage_status = {
                        "status": "ok",
                        "reason": domain_reasons.REASON_NO_CANDIDATES,
                        "duration_ms": 0.0,
                        "candidate_count": 0,
                    }

                mwe_upsert_status = self._third_pass_orchestrator.upsert_mwe_records_from_occurrences(
                    third_pass_summary.get("occurrences"),
                    request_id=request_id,
                )
                third_pass_summary["mwe_upsert_status"] = mwe_upsert_status

            if third_pass_rejected:
                rejected.extend(third_pass_rejected)

            third_pass_summary["sync_enabled"] = bool(should_sync)
            third_pass_summary["sync_stage_status"] = third_pass_sync_stage_status
            third_pass_summary["added"] = third_pass_added
            third_pass_summary["already_existed"] = third_pass_already_existed
            third_pass_summary["queued_for_sync"] = third_pass_queued
            third_pass_summary["rejected_candidates"] = third_pass_rejected
            third_pass_summary["category_review_required"] = third_pass_category_review_required
            third_pass_summary["validation_only"] = True
            third_pass_summary["validation_policy"] = dict(third_pass_policy)
        elif should_run_third_pass:
            third_pass_summary = self._third_pass_orchestrator.default_summary(
                enabled=True,
                reason=str(
                    third_pass_policy.get(
                        "reason",
                        domain_reasons.REASON_THIRD_PASS_VALIDATION_BLOCKED,
                    )
                ),
            )
            third_pass_summary["validation_only"] = True
            third_pass_summary["validation_policy"] = dict(third_pass_policy)

        table = self._table_builder.build_table(parsed, known_lemmas=known_lemmas)
        table = self._table_builder.append_occurrence_rows(
            table,
            occurrences=second_pass_summary.get("occurrences"),
            source_label="second_pass_spacy",
            known_terms=known_terms,
        )
        table = self._table_builder.append_occurrence_rows(
            table,
            occurrences=third_pass_summary.get("occurrences"),
            source_label="third_pass_llm",
            known_terms=known_terms,
        )
        table = self._table_builder.append_heuristic_phrasal_rows(
            table,
            phrasal_verbs=phrasal_verbs,
            known_terms=known_terms,
        )

        added = self._text_processor.unique(added)
        already_existed = self._text_processor.unique(already_existed)
        queued_for_sync = self._text_processor.unique(queued_for_sync)
        rejected = self._text_processor.unique(rejected)
        sync_message = self._candidate_resolver.build_sync_message(
            added=added,
            already_existed=already_existed,
            queued_for_sync=queued_for_sync,
            sync_stage_status=sync_stage_status,
        )

        summary = {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "pipeline_build": pipeline_build,
            "lexicon_file": self.lexicon_label,
            "stats": parsed["stats"],
            "phrase_matches": parsed["phrase_matches"],
            "pipeline": parsed.get("pipeline", self.parser.pipeline_status()),
            "stage_statuses": parsed.get("stage_statuses", []),
            "pipeline_status": parsed.get("pipeline_status", "ok"),
            "lexemes": lexemes,
            "phrasal_verbs": phrasal_verbs,
            "added": added,
            "already_existed": already_existed,
            "rejected_candidates": rejected,
            "queued_for_sync": queued_for_sync,
            "sync_message": sync_message,
            "request_id": request_id,
            "sync_enabled": should_sync,
            "sync_async": sync_async,
            "sync_stage_status": sync_stage_status,
            "lexicon_version": parsed.get("lexicon_version"),
            "category_review_required": category_review_required,
            "second_pass": second_pass_summary,
            "third_pass": third_pass_summary,
        }
        error_message = str(summary.get("error", "")).strip()
        status_message = f"Parse failed: {error_message}" if error_message else str(sync_message or "Parse complete.")
        payload = ParseAndSyncResultDTO(
            table=table,
            summary=summary,
            status_message=status_message,
            error_message=error_message,
        )

        self._release_request_resources(request_id=request_id)
        if payload.ok:
            return Result.ok(payload)
        return Result.fail(
            payload.error_message or payload.status_message,
            status_code="parse_failed",
            data=payload,
        )

    def _default_second_pass_summary(self, *, enabled: bool, reason: str) -> dict[str, Any]:
        return {
            "schema_version": SECOND_PASS_SCHEMA_VERSION,
            "enabled": enabled,
            "status": "skipped",
            "reason": reason,
            "model_info": {},
            "candidates_count": 0,
            "resolved_count": 0,
            "uncertain_count": 0,
            "occurrences": [],
            "stage_statuses": [],
            "cache_hit": False,
            "sync_enabled": False,
            "sync_stage_status": {
                "status": "skipped",
                "reason": domain_reasons.REASON_SECOND_PASS_NOT_SYNCED,
                "duration_ms": 0.0,
            },
            "added": [],
            "already_existed": [],
            "queued_for_sync": [],
            "rejected_candidates": [],
            "category_review_required": [],
        }

    def _run_second_pass(self, *, text: str, request_id: str, top_n: int) -> dict[str, Any]:
        parse_mwe = getattr(self.parser, "parse_mwe_text", None)
        if not callable(parse_mwe):
            return self._default_second_pass_summary(
                enabled=True,
                reason=domain_reasons.REASON_MWE_PARSER_UNAVAILABLE,
            )

        try:
            payload = parse_mwe(text, request_id=request_id, top_n=top_n, enabled=True)
        except TypeError:
            try:
                payload = parse_mwe(text)
            except Exception as exc:
                self._log_error(operation="run_second_pass.fallback_call", error=exc)
                return {
                    **self._default_second_pass_summary(
                        enabled=True,
                        reason=domain_reasons.REASON_SECOND_PASS_FAILED,
                    ),
                    "status": "failed",
                    "reason": domain_reasons.REASON_SECOND_PASS_FAILED,
                    "error": str(exc),
                }
        except Exception as exc:
            self._log_error(operation="run_second_pass", error=exc)
            return {
                **self._default_second_pass_summary(
                    enabled=True,
                    reason=domain_reasons.REASON_SECOND_PASS_FAILED,
                ),
                "status": "failed",
                "reason": domain_reasons.REASON_SECOND_PASS_FAILED,
                "error": str(exc),
            }

        if not isinstance(payload, dict):
            return {
                **self._default_second_pass_summary(
                    enabled=True,
                    reason=domain_reasons.REASON_INVALID_SECOND_PASS_PAYLOAD,
                ),
                "status": "failed",
                "reason": domain_reasons.REASON_INVALID_SECOND_PASS_PAYLOAD,
            }

        normalized = dict(payload)
        normalized.setdefault("enabled", True)
        normalized.setdefault("status", "ok")
        normalized.setdefault("reason", domain_reasons.REASON_NONE)
        normalized.setdefault("schema_version", SECOND_PASS_SCHEMA_VERSION)
        normalized.setdefault("model_info", {})
        normalized.setdefault("candidates_count", 0)
        normalized.setdefault("resolved_count", 0)
        normalized.setdefault("uncertain_count", 0)
        normalized.setdefault("occurrences", [])
        normalized.setdefault("stage_statuses", [])
        normalized.setdefault("cache_hit", False)
        normalized.setdefault("sync_enabled", False)
        normalized.setdefault(
            "sync_stage_status",
            {
                "status": "skipped",
                "reason": domain_reasons.REASON_SECOND_PASS_NOT_SYNCED,
                "duration_ms": 0.0,
            },
        )
        normalized.setdefault("added", [])
        normalized.setdefault("already_existed", [])
        normalized.setdefault("queued_for_sync", [])
        normalized.setdefault("rejected_candidates", [])
        normalized.setdefault("category_review_required", [])
        normalized.setdefault("validation_only", True)
        normalized.setdefault("validation_policy", {})
        return normalized

    def sync_single_row(
        self,
        *,
        token: str,
        normalized: str,
        lemma: str,
        categories: str,
        request_id: str | None = None,
    ) -> Result[ParseRowSyncResultDTO]:
        resolved_request_id = request_id or uuid.uuid4().hex
        candidate = self._candidate_resolver.resolve_row_sync_candidate(
            token=token,
            normalized=normalized,
            lemma=lemma,
        )
        if not candidate:
            payload = ParseRowSyncResultDTO(
                status="rejected",
                value="",
                category=self.auto_add_category,
                request_id=resolved_request_id,
                message="Row sync rejected: empty token value.",
                category_fallback_used=True,
            )
            return Result.fail(payload.message, status_code="row_rejected", data=payload)

        hinted_category = self._candidate_resolver.first_category_hint(categories)
        if not self._candidate_resolver.allow_auto_add(
            candidate,
            suggested_category=hinted_category,
        ):
            payload = ParseRowSyncResultDTO(
                status="rejected",
                value=candidate,
                category=self.auto_add_category,
                request_id=resolved_request_id,
                message=f"Row sync rejected for '{candidate}' by auto-add validation rules.",
                category_fallback_used=True,
            )
            return Result.fail(payload.message, status_code="row_rejected", data=payload)

        try:
            single_word, multi_word = self.repository.build_index()
            existing_categories = self._candidate_resolver.collect_existing_categories(single_word, multi_word)
            category_map = {item.casefold(): item for item in existing_categories if item}
            canonical_hinted = category_map.get(hinted_category.casefold(), "") if hinted_category else ""
            chosen_category, category_fallback_used = self._candidate_resolver.resolve_sync_category(
                suggested_category=canonical_hinted or hinted_category,
                existing_categories=existing_categories,
            )

            existing_for_value: set[str]
            if " " in candidate:
                key = tuple(candidate.split())
                existing_for_value = {
                    str(item).strip()
                    for item in multi_word.get(key, [])
                    if str(item).strip()
                }
            else:
                existing_for_value = {
                    str(item).strip()
                    for item in single_word.get(candidate, [])
                    if str(item).strip()
                }

            if chosen_category.casefold() in {item.casefold() for item in existing_for_value}:
                payload = ParseRowSyncResultDTO(
                    status="already_exists",
                    value=candidate,
                    category=chosen_category,
                    request_id=resolved_request_id,
                    message=(
                        f"Row sync skipped: '{candidate}' already exists in category '{chosen_category}'."
                    ),
                    category_fallback_used=category_fallback_used,
                )
                return Result.ok(payload, status_code="row_already_exists")

            try:
                self.repository.add_entry(
                    category=chosen_category,
                    value=candidate,
                    source="auto",
                    confidence=1.0,
                    request_id=resolved_request_id,
                )
            except TypeError:
                self.repository.add_entry(category=chosen_category, value=candidate)
            self.repository.save()

            payload = ParseRowSyncResultDTO(
                status="added",
                value=candidate,
                category=chosen_category,
                request_id=resolved_request_id,
                message=(
                    f"Row sync added '{candidate}' to category '{chosen_category}' "
                    "(source=auto, status=pending_review)."
                ),
                category_fallback_used=category_fallback_used,
            )
            return Result.ok(payload, status_code="row_added")
        except Exception as exc:  # pragma: no cover - defensive for UI flow
            self._log_error(operation="sync_single_row", error=exc)
            payload = ParseRowSyncResultDTO(
                status="error",
                value=candidate,
                category=self.auto_add_category,
                request_id=resolved_request_id,
                message=f"Row sync failed: {exc}",
                category_fallback_used=True,
            )
            return Result.fail(payload.message, status_code="row_sync_exception", data=payload)

    def _parse_with_request_id(self, *, text: str, request_id: str) -> dict[str, Any]:
        try:
            return self.parser.parse_text(text, request_id=request_id)
        except TypeError:
            return self.parser.parse_text(text)

    def _release_request_resources(self, *, request_id: str) -> None:
        release = getattr(self.parser, "release_request_resources", None)
        if not callable(release):
            return
        try:
            release(request_id=request_id)
        except TypeError:
            try:
                release(request_id)
            except Exception as exc:
                self._log_error(operation="release_request_resources.fallback_call", error=exc)
        except Exception as exc:
            self._log_error(operation="release_request_resources", error=exc)

    def close(self, *, timeout_seconds: float | None = None) -> None:
        if self._async_queue is not None:
            resolved_timeout_seconds = (
                max(0.1, float(timeout_seconds))
                if timeout_seconds is not None
                else max(1.0, self.settings.sync_timeout_ms / 1000.0)
            )
            idle_before_shutdown = self._async_queue.wait_for_idle(
                timeout_seconds=resolved_timeout_seconds
            )
            report = self._async_queue.shutdown(
                drain=idle_before_shutdown,
                timeout_seconds=resolved_timeout_seconds,
            )
            report["idle_before_shutdown"] = idle_before_shutdown
            report["force_shutdown"] = not idle_before_shutdown
            self._log_info(f"parse_async_queue_shutdown: {report}")
            self._async_queue = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception as exc:
            self._log_error(operation="parse_and_sync.__del__", error=exc)
