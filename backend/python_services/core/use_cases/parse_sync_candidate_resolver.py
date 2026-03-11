from __future__ import annotations

import time
from typing import Any, Callable

from backend.python_services.core.domain import ICategoryRepository, ILexiconRepository, ParseSyncSettings
import backend.python_services.core.domain.reason_codes as domain_reasons
from backend.python_services.core.domain.services import AsyncSyncJob, ISyncQueue, POS_CATEGORY_HINTS, TextProcessor


AUTO_CREATE_SYNC_CATEGORIES = set(POS_CATEGORY_HINTS.values()) | {"Idiom", "Phrasal Verb"}
_ErrorLogger = Callable[[str, Exception], None]


class SyncCandidateResolver:
    """Resolve parsed candidates into lexicon sync actions."""

    def __init__(
        self,
        *,
        repository: ILexiconRepository,
        category_repository: ICategoryRepository,
        settings: ParseSyncSettings,
        auto_add_category: str,
        text_processor: TextProcessor,
        persistent_queue_enabled: bool = False,
        log_error: _ErrorLogger | None = None,
    ) -> None:
        self._repository = repository
        self._category_repository = category_repository
        self._settings = settings
        self._text_processor = text_processor
        self._persistent_queue_enabled = bool(persistent_queue_enabled)
        self._auto_add_category = str(auto_add_category or "").strip() or "Auto Added"
        self._log_error_callback = log_error

    def load_known_terms_from_repository(self) -> tuple[set[str], set[str]]:
        known_lemmas, existing_single, existing_multi, _ = self.load_sync_index_state()
        known_terms: set[str] = set()
        known_terms.update(
            normed
            for item in existing_single
            if (normed := self._text_processor.normalize_term(item))
        )
        known_terms.update(
            normed
            for item in existing_multi
            if (normed := self._text_processor.normalize_term(item))
        )
        return known_lemmas, known_terms

    def load_sync_index_state(self) -> tuple[set[str], set[str], set[str], set[str]]:
        try:
            single_word, multi_word = self._repository.build_index()
        except Exception as exc:
            self._log_error("load_sync_index_state", exc)
            return set(), set(), set(), set()

        known_lemmas: set[str] = set()
        for value in single_word.keys():
            normalized = self._text_processor.normalize_lexeme(str(value))
            if normalized:
                known_lemmas.add(normalized)

        existing_single = set(single_word.keys())
        existing_multi = {" ".join(parts) for parts in multi_word.keys()}
        existing_categories = self.collect_existing_categories(single_word, multi_word)
        return known_lemmas, existing_single, existing_multi, existing_categories

    def sync_candidates(
        self,
        candidates: list[str],
        *,
        request_id: str,
        candidate_categories: dict[str, str] | None = None,
        existing_single: set[str] | None = None,
        existing_multi: set[str] | None = None,
        existing_categories: set[str] | None = None,
    ) -> tuple[list[str], list[str], dict[str, object], list[dict[str, str]]]:
        stage_start = time.perf_counter()

        if existing_single is None or existing_multi is None or existing_categories is None:
            single_word, multi_word = self._repository.build_index()
            existing_single = set(single_word.keys())
            existing_multi = {" ".join(parts) for parts in multi_word.keys()}
            existing_categories = self.collect_existing_categories(single_word, multi_word)

        added: list[str] = []
        already_existed: list[str] = []
        category_review_required: list[dict[str, str]] = []
        to_insert: list[tuple[str, str]] = []
        timed_out = False

        for candidate in candidates:
            elapsed_ms = (time.perf_counter() - stage_start) * 1000.0
            if elapsed_ms > self._settings.sync_timeout_ms:
                timed_out = True
                break

            exists = candidate in existing_multi if " " in candidate else candidate in existing_single
            if exists:
                already_existed.append(candidate)
                continue

            suggested_category = (
                candidate_categories.get(candidate, self._auto_add_category)
                if candidate_categories is not None
                else self._auto_add_category
            )
            chosen_category, category_fallback_used = self.resolve_sync_category(
                suggested_category=suggested_category,
                existing_categories=existing_categories,
            )
            if category_fallback_used and suggested_category != self._auto_add_category:
                category_review_required.append(
                    {
                        "candidate": candidate,
                        "suggested_category": suggested_category,
                        "status": "manual_category_required",
                    }
                )

            to_insert.append((chosen_category, candidate))
            added.append(candidate)

            if " " in candidate:
                existing_multi.add(candidate)
            else:
                existing_single.add(candidate)
            existing_categories.add(chosen_category)

        if added:
            inserted_with_bulk = False
            try:
                self._repository.add_entries(
                    entries=to_insert,
                    source="auto",
                    confidence=1.0,
                    request_id=request_id,
                )
                inserted_with_bulk = True
            except TypeError:
                inserted_with_bulk = False

            if not inserted_with_bulk:
                for category, candidate in to_insert:
                    try:
                        self._repository.add_entry(
                            category=category,
                            value=candidate,
                            source="auto",
                            confidence=1.0,
                            request_id=request_id,
                        )
                    except TypeError:
                        self._repository.add_entry(category=category, value=candidate)

            self._repository.save()

        duration_ms = (time.perf_counter() - stage_start) * 1000.0
        status = "timed_out" if timed_out else "ok"
        reason = (
            domain_reasons.REASON_SYNC_TIMEOUT_EXCEEDED
            if timed_out
            else domain_reasons.REASON_NONE
        )
        return (
            added,
            already_existed,
            {
                "status": status,
                "reason": reason,
                "duration_ms": round(duration_ms, 3),
                "candidate_count": len(candidates),
                "added_count": len(added),
                "already_existed_count": len(already_existed),
                "rejected_count": 0,
                "category_review_required_count": len(category_review_required),
            },
            category_review_required,
        )

    def partition_sync_candidates(
        self,
        candidates: list[str],
        *,
        candidate_categories: dict[str, str] | None = None,
    ) -> tuple[list[str], list[str]]:
        accepted: list[str] = []
        rejected: list[str] = []
        accepted_seen: set[str] = set()
        rejected_seen: set[str] = set()

        for candidate in candidates:
            canonical_candidate = self._text_processor.canonicalize_expression(candidate)
            if not canonical_candidate:
                continue
            suggested_category = ""
            if candidate_categories is not None:
                suggested_category = str(
                    candidate_categories.get(candidate, "")
                    or candidate_categories.get(canonical_candidate, "")
                ).strip()

            if self.allow_auto_add(canonical_candidate, suggested_category=suggested_category):
                if canonical_candidate not in accepted_seen:
                    accepted.append(canonical_candidate)
                    accepted_seen.add(canonical_candidate)
            else:
                if canonical_candidate not in rejected_seen:
                    rejected.append(canonical_candidate)
                    rejected_seen.add(canonical_candidate)

        return accepted, rejected

    def enqueue_async_sync(
        self,
        accepted_candidates: list[str],
        *,
        request_id: str,
        candidate_categories: dict[str, str] | None = None,
        async_queue: ISyncQueue | None,
    ) -> tuple[list[str], dict[str, object]]:
        if not accepted_candidates:
            return [], {
                "status": "ok",
                "reason": domain_reasons.REASON_NO_CANDIDATES,
                "duration_ms": 0.0,
                "candidate_count": 0,
                "queued_count": 0,
            }

        if async_queue is None:
            return [], {
                "status": "failed",
                "reason": domain_reasons.REASON_ASYNC_QUEUE_UNAVAILABLE,
                "duration_ms": 0.0,
                "candidate_count": len(accepted_candidates),
                "queued_count": 0,
            }

        job = AsyncSyncJob(
            request_id=request_id,
            candidates=tuple(accepted_candidates),
            auto_add_category=self._auto_add_category,
            candidate_categories=tuple(
                (
                    candidate,
                    (
                        candidate_categories.get(candidate, self._auto_add_category)
                        if candidate_categories is not None
                        else self._auto_add_category
                    ),
                )
                for candidate in accepted_candidates
            ),
        )

        started = time.perf_counter()
        accepted, depth = async_queue.enqueue(job)
        duration_ms = (time.perf_counter() - started) * 1000.0
        if not accepted:
            return [], {
                "status": "rejected",
                "reason": domain_reasons.REASON_QUEUE_FULL,
                "duration_ms": round(duration_ms, 3),
                "queue_depth": depth,
                "candidate_count": len(accepted_candidates),
                "queued_count": 0,
                "http_status_code": self._settings.api_reject_status_code,
            }

        queue_reason = (
            domain_reasons.REASON_ASYNC_SYNC_ENABLED_PERSISTENT
            if self._persistent_queue_enabled
            else domain_reasons.REASON_ASYNC_SYNC_ENABLED_INMEMORY
        )
        return accepted_candidates, {
            "status": "queued",
            "reason": queue_reason,
            "duration_ms": round(duration_ms, 3),
            "queue_depth": depth,
            "candidate_count": len(accepted_candidates),
            "queued_count": len(accepted_candidates),
        }

    def process_async_sync_job(self, job: AsyncSyncJob) -> dict[str, object]:
        candidate_categories = dict(job.candidate_categories)
        added, already_existed, status, category_review_required = self.sync_candidates(
            list(job.candidates),
            request_id=job.request_id,
            candidate_categories=candidate_categories,
        )
        return {
            "added_count": len(added),
            "already_existed_count": len(already_existed),
            "status": status,
            "category_review_required_count": len(category_review_required),
        }

    def build_sync_message(
        self,
        *,
        added: list[str],
        already_existed: list[str],
        queued_for_sync: list[str],
        sync_stage_status: dict[str, object],
    ) -> str:
        message = self._text_processor.format_sync_message(added, already_existed)
        if queued_for_sync:
            lines = ["queued for async sync:"]
            lines.extend([f"- {item}" for item in queued_for_sync])
            message = f"{message}\n" + "\n".join(lines)
        elif str(sync_stage_status.get("status")) == "rejected":
            message = f"{message}\nasync sync queue is full; request not enqueued."
        return message

    def allow_auto_add(self, candidate: str, *, suggested_category: str = "") -> bool:
        return self._text_processor.allow_auto_add(
            candidate,
            suggested_category=suggested_category,
        )

    def build_candidate_categories(
        self,
        parsed_tokens: list[dict[str, Any]],
        phrasal_verbs: list[str],
    ) -> dict[str, str]:
        return self._text_processor.build_candidate_categories(
            parsed_tokens,
            phrasal_verbs,
            auto_add_category=self._auto_add_category,
        )

    def canonicalize_candidate_categories(
        self,
        candidate_categories: dict[str, str] | None,
    ) -> dict[str, str] | None:
        if candidate_categories is None:
            return None
        normalized: dict[str, str] = {}
        for raw_candidate, raw_category in candidate_categories.items():
            canonical = self._text_processor.canonicalize_expression(raw_candidate)
            if not canonical:
                continue
            category = str(raw_category or "").strip() or self._auto_add_category
            normalized.setdefault(canonical, category)
        return normalized

    def category_from_token(self, token: dict[str, Any]) -> str:
        return self._text_processor.category_from_token(token)

    @staticmethod
    def first_category_hint(categories: str) -> str:
        for item in str(categories or "").split(","):
            category = str(item).strip()
            if category and category != "-":
                return category
        return ""

    def resolve_row_sync_candidate(self, *, token: str, normalized: str, lemma: str) -> str:
        probes = [
            self._text_processor.canonicalize_expression(normalized),
            self._text_processor.canonicalize_expression(token),
            self._text_processor.normalize_lexeme(lemma),
            self._text_processor.normalize_lexeme(normalized),
            self._text_processor.normalize_lexeme(token),
        ]
        fallback = ""
        for probe in probes:
            candidate = str(probe or "").strip().lower()
            if not candidate or candidate == "-":
                continue
            if not fallback:
                fallback = candidate
            if self.allow_auto_add(candidate):
                return candidate
        return fallback

    def resolve_sync_category(
        self,
        *,
        suggested_category: str,
        existing_categories: set[str],
    ) -> tuple[str, bool]:
        clean_suggested = str(suggested_category or "").strip()
        if not clean_suggested:
            return self._auto_add_category, True
        if clean_suggested in existing_categories:
            return clean_suggested, False
        if clean_suggested in AUTO_CREATE_SYNC_CATEGORIES:
            if self.ensure_category_exists(clean_suggested, existing_categories):
                return clean_suggested, False
        return self._auto_add_category, True

    def ensure_category_exists(self, category: str, existing_categories: set[str]) -> bool:
        clean_category = str(category or "").strip()
        if not clean_category:
            return False
        if clean_category in existing_categories:
            return True
        try:
            mutation = self._category_repository.create_category(clean_category)
            categories_payload = getattr(mutation, "categories", [])
            if isinstance(categories_payload, list):
                for item in categories_payload:
                    cleaned = str(item).strip()
                    if cleaned:
                        existing_categories.add(cleaned)
        except Exception as exc:
            self._log_error("ensure_category_exists", exc)
        if clean_category in existing_categories:
            return True
        existing_categories.add(clean_category)
        return True

    def collect_existing_categories(
        self,
        single_word: dict[str, list[str]],
        multi_word: dict[tuple[str, ...], list[str]],
    ) -> set[str]:
        categories: set[str] = set()
        for values in single_word.values():
            categories.update(str(item).strip() for item in values if str(item).strip())
        for values in multi_word.values():
            categories.update(str(item).strip() for item in values if str(item).strip())

        try:
            repo_categories = self._category_repository.list_categories()
            categories.update(str(item).strip() for item in repo_categories if str(item).strip())
        except Exception as exc:
            self._log_error("collect_existing_categories", exc)

        return categories

    def _log_error(self, operation: str, error: Exception) -> None:
        if self._log_error_callback is not None:
            self._log_error_callback(operation, error)
