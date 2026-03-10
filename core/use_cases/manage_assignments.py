from __future__ import annotations

from dataclasses import replace
from typing import Protocol
import uuid

from core.domain import (
    AssignmentBulkOperationResultDTO,
    AssignmentRecord,
    AssignmentScanResultDTO,
    IAssignmentRepository,
    ILexiconRepository,
    ILoggingService,
    ISentenceExtractor,
    ParseAndSyncResultDTO,
    ParseRowSyncResultDTO,
    QuickAddSuggestionDTO,
    Result,
)
from core.domain.services import AssignmentScannerService, TextProcessor
from core.domain.services.text_processor import PHRASAL_PARTICLES
from core.use_cases._base import BaseInteractor


class AssignmentLexiconSyncPort(Protocol):
    def execute(
        self,
        text: str,
        *,
        sync: bool | None = None,
        third_pass_enabled: bool | None = None,
        think_mode: bool | None = None,
    ) -> Result[ParseAndSyncResultDTO]: ...


class ManageAssignmentsInteractor(BaseInteractor):
    def __init__(
        self,
        *,
        assignment_repository: IAssignmentRepository,
        scanner_service: AssignmentScannerService,
        lexicon_repository: ILexiconRepository,
        completed_threshold_percent: float = 90.0,
        auto_add_category: str = "Auto Added",
        assignment_sync_use_case: AssignmentLexiconSyncPort | None = None,
        sentence_extractor: ISentenceExtractor | None = None,
        logger: ILoggingService | None = None,
        text_processor: TextProcessor | None = None,
    ) -> None:
        self._assignment_repository = assignment_repository
        self._scanner_service = scanner_service
        self._lexicon_repository = lexicon_repository
        self._completed_threshold_percent = max(0.0, min(100.0, float(completed_threshold_percent)))
        self._auto_add_category = str(auto_add_category or "").strip() or "Auto Added"
        self._assignment_sync_use_case = assignment_sync_use_case
        self._sentence_extractor = sentence_extractor
        self._logger = logger
        self._text_processor = text_processor or TextProcessor()

    def scan_and_save(
        self,
        *,
        title: str,
        content_original: str,
        content_completed: str,
    ) -> Result[AssignmentScanResultDTO]:
        if not str(content_completed or "").strip():
            return Result.fail(
                "Completed assignment text is empty.",
                status_code="assignment_empty_completed_text",
            )
        try:
            saved = self._assignment_repository.save_assignment(
                title=str(title or "").strip() or "Untitled Assignment",
                content_original=str(content_original or ""),
                content_completed=str(content_completed or ""),
            )
            self._sync_assignment_text_to_lexicon(
                assignment_id=int(saved.id),
                content_completed=str(saved.content_completed),
                operation="scan_and_save",
            )
            payload = self._scan_and_apply_status(
                assignment_id=int(saved.id),
                title=str(saved.title),
                content_original=str(saved.content_original),
                content_completed=str(saved.content_completed),
            )
            self._log_info(
                "assignment_scan_and_save: "
                f"id={saved.id}, status={payload.assignment_status}, words={payload.word_count}, "
                f"matches={len(payload.matches)}, missing={len(payload.missing_words)}, "
                f"coverage={payload.lexicon_coverage_percent:.2f}, duration_ms={payload.duration_ms}"
            )
            return Result.ok(payload)
        except Exception as exc:
            self._log_error(operation="assignment_scan_and_save", error=exc)
            return Result.fail(
                f"Assignment scan failed: {exc}",
                status_code="assignment_scan_exception",
            )

    def get_assignment(self, *, assignment_id: int) -> Result[AssignmentRecord]:
        safe_id = int(assignment_id)
        if safe_id <= 0:
            return Result.fail(
                "Invalid assignment id.",
                status_code="assignment_invalid_id",
            )
        try:
            row = self._assignment_repository.get_assignment(assignment_id=safe_id)
            if row is None:
                return Result.fail(
                    f"Assignment #{safe_id} not found.",
                    status_code="assignment_not_found",
                )
            return Result.ok(row)
        except Exception as exc:
            self._log_error(operation="assignment_get", error=exc)
            return Result.fail(
                f"Assignment get failed: {exc}",
                status_code="assignment_get_exception",
            )

    def update_assignment(
        self,
        *,
        assignment_id: int,
        title: str,
        content_original: str,
        content_completed: str,
    ) -> Result[AssignmentScanResultDTO]:
        safe_id = int(assignment_id)
        if safe_id <= 0:
            return Result.fail(
                "Invalid assignment id.",
                status_code="assignment_invalid_id",
            )
        if not str(content_completed or "").strip():
            return Result.fail(
                "Completed assignment text is empty.",
                status_code="assignment_empty_completed_text",
            )
        try:
            updated = self._assignment_repository.update_assignment_content(
                assignment_id=safe_id,
                title=str(title or "").strip() or "Untitled Assignment",
                content_original=str(content_original or ""),
                content_completed=str(content_completed or ""),
            )
            if updated is None:
                return Result.fail(
                    f"Assignment #{safe_id} not found.",
                    status_code="assignment_not_found",
                )
            self._sync_assignment_text_to_lexicon(
                assignment_id=int(updated.id),
                content_completed=str(updated.content_completed),
                operation="update_assignment",
            )
            payload = self._scan_and_apply_status(
                assignment_id=int(updated.id),
                title=str(updated.title),
                content_original=str(updated.content_original),
                content_completed=str(updated.content_completed),
            )
            self._log_info(
                "assignment_update: "
                f"id={updated.id}, status={payload.assignment_status}, words={payload.word_count}, "
                f"matches={len(payload.matches)}, missing={len(payload.missing_words)}, "
                f"coverage={payload.lexicon_coverage_percent:.2f}, duration_ms={payload.duration_ms}"
            )
            return Result.ok(payload)
        except Exception as exc:
            self._log_error(operation="assignment_update", error=exc)
            return Result.fail(
                f"Assignment update failed: {exc}",
                status_code="assignment_update_exception",
            )

    def delete_assignment(self, *, assignment_id: int) -> Result[bool]:
        safe_id = int(assignment_id)
        if safe_id <= 0:
            return Result.fail(
                "Invalid assignment id.",
                status_code="assignment_invalid_id",
                data=False,
            )
        try:
            deleted = bool(self._assignment_repository.delete_assignment(assignment_id=safe_id))
            if not deleted:
                return Result.fail(
                    f"Assignment #{safe_id} not found.",
                    status_code="assignment_not_found",
                    data=False,
                )
            self._log_info(f"assignment_delete: id={safe_id}, deleted=yes")
            return Result.ok(True, status_code="assignment_deleted")
        except Exception as exc:
            self._log_error(operation="assignment_delete", error=exc)
            return Result.fail(
                f"Assignment delete failed: {exc}",
                status_code="assignment_delete_exception",
                data=False,
            )

    def list_assignments(self, *, limit: int = 50, offset: int = 0) -> Result[list[AssignmentRecord]]:
        try:
            rows = self._assignment_repository.list_assignments(
                limit=max(1, int(limit)),
                offset=max(0, int(offset)),
            )
            self._log_info(f"assignment_list: rows={len(rows)}")
            return Result.ok(rows)
        except Exception as exc:
            self._log_error(operation="assignment_list", error=exc)
            return Result.fail(
                f"Assignment list failed: {exc}",
                status_code="assignment_list_exception",
            )

    def suggest_quick_add(
        self,
        *,
        term: str,
        content_completed: str,
        available_categories: list[str] | None = None,
    ) -> Result[QuickAddSuggestionDTO]:
        cleaned_term = self._text_processor.normalize_term(term)
        if not cleaned_term:
            return Result.fail(
                "Quick Add suggestion failed: empty word.",
                status_code="assignment_quick_add_suggest_empty",
            )
        try:
            suggested_categories, rationale, confidence = self._infer_quick_add_category_order(cleaned_term)
            resolved_categories = self._resolve_suggested_categories(
                suggested=suggested_categories,
                available_categories=available_categories,
            )
            recommended = resolved_categories[0] if resolved_categories else self._auto_add_category
            if suggested_categories and recommended.casefold() != suggested_categories[0].casefold():
                confidence = min(confidence, 0.58)
                rationale = f"{rationale} Adjusted to available category list."
            payload = QuickAddSuggestionDTO(
                term=cleaned_term,
                recommended_category=recommended,
                candidate_categories=tuple(resolved_categories),
                confidence=round(max(0.0, min(1.0, float(confidence))), 2),
                rationale=rationale,
                suggested_example_usage=self._extract_sentence(
                    content=content_completed,
                    term=cleaned_term,
                ),
            )
            return Result.ok(payload)
        except Exception as exc:
            self._log_error(operation="assignment_quick_add_suggest", error=exc)
            return Result.fail(
                f"Quick Add suggestion failed: {exc}",
                status_code="assignment_quick_add_suggest_exception",
            )

    def bulk_delete_assignments(
        self,
        *,
        assignment_ids: list[int],
    ) -> Result[AssignmentBulkOperationResultDTO]:
        normalized_ids = self._normalize_assignment_ids(assignment_ids)
        if not normalized_ids:
            payload = AssignmentBulkOperationResultDTO(
                operation="bulk_delete",
                requested_ids=tuple(),
                processed_ids=tuple(),
                failed_ids=tuple(),
                success_count=0,
                failed_count=0,
                message="Select one or more assignments first.",
                failure_details=tuple(),
            )
            return Result.fail(
                payload.message,
                status_code="assignment_bulk_delete_empty",
                data=payload,
            )

        processed_ids: list[int] = []
        failed_ids: list[int] = []
        failure_details: list[str] = []
        try:
            deleted_ids, not_found_ids = self._assignment_repository.bulk_delete_assignments(
                ids=normalized_ids
            )
            processed_ids = deleted_ids
            failed_ids = not_found_ids
            failure_details = [f"#{i}: not found" for i in not_found_ids]
        except Exception as exc:
            failed_ids = normalized_ids
            failure_details = [f"bulk delete failed: {exc}"]

        payload = self._build_bulk_result(
            operation="bulk_delete",
            requested_ids=normalized_ids,
            processed_ids=processed_ids,
            failed_ids=failed_ids,
            failure_details=failure_details,
        )
        self._log_info(
            "assignment_bulk_delete: "
            f"requested={len(normalized_ids)}, success={payload.success_count}, failed={payload.failed_count}"
        )
        if payload.success_count <= 0:
            return Result.fail(
                payload.message,
                status_code="assignment_bulk_delete_failed",
                data=payload,
            )
        if payload.failed_count > 0:
            return Result.ok(payload, status_code="assignment_bulk_delete_partial")
        return Result.ok(payload, status_code="assignment_bulk_delete_completed")

    def bulk_rescan_assignments(
        self,
        *,
        assignment_ids: list[int],
    ) -> Result[AssignmentBulkOperationResultDTO]:
        normalized_ids = self._normalize_assignment_ids(assignment_ids)
        if not normalized_ids:
            payload = AssignmentBulkOperationResultDTO(
                operation="bulk_rescan",
                requested_ids=tuple(),
                processed_ids=tuple(),
                failed_ids=tuple(),
                success_count=0,
                failed_count=0,
                message="Select one or more assignments first.",
                failure_details=tuple(),
            )
            return Result.fail(
                payload.message,
                status_code="assignment_bulk_rescan_empty",
                data=payload,
            )

        processed_ids: list[int] = []
        failed_ids: list[int] = []
        failure_details: list[str] = []
        for assignment_id in normalized_ids:
            try:
                record = self._assignment_repository.get_assignment(assignment_id=assignment_id)
            except Exception as exc:
                failed_ids.append(assignment_id)
                failure_details.append(f"#{assignment_id}: {exc}")
                continue
            if record is None:
                failed_ids.append(assignment_id)
                failure_details.append(f"#{assignment_id}: not found")
                continue
            try:
                self._sync_assignment_text_to_lexicon(
                    assignment_id=int(record.id),
                    content_completed=str(record.content_completed),
                    operation="bulk_rescan",
                )
                self._scan_and_apply_status(
                    assignment_id=int(record.id),
                    title=str(record.title),
                    content_original=str(record.content_original),
                    content_completed=str(record.content_completed),
                )
            except Exception as exc:
                failed_ids.append(assignment_id)
                failure_details.append(f"#{assignment_id}: {exc}")
                continue
            processed_ids.append(assignment_id)

        payload = self._build_bulk_result(
            operation="bulk_rescan",
            requested_ids=normalized_ids,
            processed_ids=processed_ids,
            failed_ids=failed_ids,
            failure_details=failure_details,
        )
        self._log_info(
            "assignment_bulk_rescan: "
            f"requested={len(normalized_ids)}, success={payload.success_count}, failed={payload.failed_count}"
        )
        if payload.success_count <= 0:
            return Result.fail(
                payload.message,
                status_code="assignment_bulk_rescan_failed",
                data=payload,
            )
        if payload.failed_count > 0:
            return Result.ok(payload, status_code="assignment_bulk_rescan_partial")
        return Result.ok(payload, status_code="assignment_bulk_rescan_completed")

    def auto_rescan_all_assignments(
        self,
        *,
        reason: str = "auto",
    ) -> Result[AssignmentBulkOperationResultDTO]:
        """List all saved assignments and bulk-rescan them. Returns noop OK if none exist."""
        try:
            listed = self._assignment_repository.list_assignments(limit=5000, offset=0)
        except Exception as exc:
            self._log_error(operation="auto_rescan_all_assignments.list", error=exc)
            payload = AssignmentBulkOperationResultDTO(
                operation="auto_rescan",
                requested_ids=tuple(),
                processed_ids=tuple(),
                failed_ids=tuple(),
                success_count=0,
                failed_count=0,
                message=f"Auto-rescan skipped ({reason}): assignments list unavailable.",
                failure_details=tuple(),
            )
            return Result.fail(payload.message, status_code="assignment_auto_rescan_list_failed", data=payload)

        assignment_ids = self._normalize_assignment_ids(
            [int(item.id) for item in listed if isinstance(item, AssignmentRecord)]
        )
        if not assignment_ids:
            payload = AssignmentBulkOperationResultDTO(
                operation="auto_rescan",
                requested_ids=tuple(),
                processed_ids=tuple(),
                failed_ids=tuple(),
                success_count=0,
                failed_count=0,
                message=f"Auto-rescan skipped ({reason}): no saved assignments.",
                failure_details=tuple(),
            )
            return Result.ok(payload, status_code="assignment_auto_rescan_noop")

        result = self.bulk_rescan_assignments(assignment_ids=assignment_ids)
        if result.data is not None and isinstance(result.data, AssignmentBulkOperationResultDTO):
            patched = AssignmentBulkOperationResultDTO(
                operation="auto_rescan",
                requested_ids=result.data.requested_ids,
                processed_ids=result.data.processed_ids,
                failed_ids=result.data.failed_ids,
                success_count=result.data.success_count,
                failed_count=result.data.failed_count,
                message=result.data.message,
                failure_details=result.data.failure_details,
            )
            return Result.ok(patched, status_code=result.status_code or "assignment_auto_rescan_completed") \
                if result.success else Result.fail(
                    result.error_message or patched.message,
                    status_code=result.status_code or "assignment_auto_rescan_failed",
                    data=patched,
                )
        return result

    def quick_add_missing_word(
        self,
        *,
        assignment_id: int | None,
        term: str,
        content_completed: str,
        category: str = "",
    ) -> Result[ParseRowSyncResultDTO]:
        cleaned_term = str(term or "").strip().casefold()
        if not cleaned_term:
            payload = ParseRowSyncResultDTO(
                status="rejected",
                value="",
                category=self._auto_add_category,
                request_id="",
                message="Quick Add rejected: empty word.",
                category_fallback_used=True,
            )
            return Result.fail(payload.message, status_code="assignment_quick_add_rejected", data=payload)
        chosen_category = str(category or "").strip() or self._auto_add_category
        if not self._text_processor.allow_auto_add(
            cleaned_term,
            suggested_category=chosen_category,
        ):
            payload = ParseRowSyncResultDTO(
                status="rejected",
                value=cleaned_term,
                category=chosen_category,
                request_id="",
                message=f"Quick Add rejected for '{cleaned_term}' by validation rules.",
                category_fallback_used=False,
            )
            return Result.fail(payload.message, status_code="assignment_quick_add_rejected", data=payload)
        request_id = uuid.uuid4().hex
        try:
            if self._exists_in_category(term=cleaned_term, category=chosen_category):
                payload = ParseRowSyncResultDTO(
                    status="already_exists",
                    value=cleaned_term,
                    category=chosen_category,
                    request_id=request_id,
                    message=(
                        f"Quick Add skipped: '{cleaned_term}' already exists in category '{chosen_category}'."
                    ),
                    category_fallback_used=False,
                )
                return Result.ok(payload, status_code="row_already_exists")

            example_usage = self._extract_sentence(content=content_completed, term=cleaned_term)
            self._lexicon_repository.add_entry(
                category=chosen_category,
                value=cleaned_term,
                source="manual",
                confidence=1.0,
                request_id=request_id,
                example_usage=example_usage,
            )
            self._lexicon_repository.save()
            payload = ParseRowSyncResultDTO(
                status="added",
                value=cleaned_term,
                category=chosen_category,
                request_id=request_id,
                message=(
                    f"Quick Add added '{cleaned_term}' to '{chosen_category}'"
                    + (" with example usage." if example_usage else ".")
                ),
                category_fallback_used=False,
            )
            self._log_info(
                "assignment_quick_add: "
                f"assignment_id={assignment_id}, term={cleaned_term}, category={chosen_category}, "
                f"example_saved={'yes' if bool(example_usage) else 'no'}"
            )
            return Result.ok(payload, status_code="row_added")
        except Exception as exc:
            self._log_error(operation="assignment_quick_add", error=exc)
            payload = ParseRowSyncResultDTO(
                status="error",
                value=cleaned_term,
                category=chosen_category,
                request_id=request_id,
                message=f"Quick Add failed: {exc}",
                category_fallback_used=False,
            )
            return Result.fail(payload.message, status_code="assignment_quick_add_exception", data=payload)

    def _infer_quick_add_category_order(self, term: str) -> tuple[list[str], str, float]:
        parts = [item for item in str(term or "").split(" ") if item]
        if len(parts) > 1 and parts[-1] in PHRASAL_PARTICLES:
            return (
                ["Phrasal Verb", "Verb", self._auto_add_category],
                "Detected a multi-word expression ending with a phrasal particle.",
                0.91,
            )
        if len(parts) > 1 and len(parts) >= 3:
            return (
                ["Idiom", self._auto_add_category],
                "Detected a multi-word expression likely used as an idiom.",
                0.74,
            )
        base = parts[0] if parts else ""
        if base in PHRASAL_PARTICLES:
            return (
                ["Particle", "Preposition", self._auto_add_category],
                "Detected a particle/preposition candidate token.",
                0.78,
            )
        if base.endswith("ly"):
            return (
                ["Adverb", self._auto_add_category],
                "Detected an adverb-like suffix (-ly).",
                0.72,
            )
        if base.endswith("ing") or base.endswith("ed"):
            return (
                ["Verb", self._auto_add_category],
                "Detected a verb-like inflection suffix (-ing/-ed).",
                0.68,
            )
        if base.endswith(("tion", "ment", "ness", "ity", "ship", "ism", "age")):
            return (
                ["Noun", self._auto_add_category],
                "Detected a noun-like derivational suffix.",
                0.66,
            )
        return (
            [self._auto_add_category, "Noun", "Verb"],
            "No strong morphological signal detected; using safe default.",
            0.5,
        )

    def _resolve_suggested_categories(
        self,
        *,
        suggested: list[str],
        available_categories: list[str] | None,
    ) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        available: list[str] = []
        available_map: dict[str, str] = {}
        if isinstance(available_categories, list):
            for raw in available_categories:
                item = str(raw or "").strip()
                if not item:
                    continue
                casefold_item = item.casefold()
                if casefold_item in available_map:
                    continue
                available_map[casefold_item] = item
                available.append(item)

        for candidate in [*suggested, self._auto_add_category]:
            clean_candidate = str(candidate or "").strip()
            if not clean_candidate:
                continue
            if available:
                resolved = available_map.get(clean_candidate.casefold(), "")
            else:
                resolved = clean_candidate
            if not resolved:
                continue
            casefold_resolved = resolved.casefold()
            if casefold_resolved in seen:
                continue
            seen.add(casefold_resolved)
            output.append(resolved)

        if available:
            if not output:
                output.append(available[0])
            return output
        if not output:
            output.append(self._auto_add_category)
        return output

    def _normalize_assignment_ids(self, assignment_ids: list[int]) -> list[int]:
        output: list[int] = []
        seen: set[int] = set()
        for raw_id in assignment_ids:
            try:
                safe_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if safe_id <= 0 or safe_id in seen:
                continue
            seen.add(safe_id)
            output.append(safe_id)
        return output

    def _build_bulk_result(
        self,
        *,
        operation: str,
        requested_ids: list[int],
        processed_ids: list[int],
        failed_ids: list[int],
        failure_details: list[str],
    ) -> AssignmentBulkOperationResultDTO:
        success_count = len(processed_ids)
        failed_count = len(failed_ids)
        pretty_operation = "Bulk delete" if operation == "bulk_delete" else "Bulk rescan"
        message = f"{pretty_operation}: {success_count} succeeded, {failed_count} failed."
        if failure_details:
            preview = "; ".join(failure_details[:3])
            if len(failure_details) > 3:
                preview = f"{preview}; ..."
            message = f"{message} {preview}"
        return AssignmentBulkOperationResultDTO(
            operation=operation,
            requested_ids=tuple(requested_ids),
            processed_ids=tuple(processed_ids),
            failed_ids=tuple(failed_ids),
            success_count=success_count,
            failed_count=failed_count,
            message=message,
            failure_details=tuple(failure_details),
        )

    def _scan_and_apply_status(
        self,
        *,
        assignment_id: int,
        title: str,
        content_original: str,
        content_completed: str,
    ) -> AssignmentScanResultDTO:
        scan = self._scanner_service.scan(
            title=str(title),
            content_original=str(content_original),
            content_completed=str(content_completed),
        )
        next_status = self._resolve_assignment_status(scan.lexicon_coverage_percent)
        persisted = self._assignment_repository.update_assignment_status(
            assignment_id=int(assignment_id),
            status=next_status,
            lexicon_coverage_percent=float(scan.lexicon_coverage_percent),
        )
        final_status = str(persisted.status if persisted is not None else next_status)
        return replace(
            scan,
            assignment_id=int(assignment_id),
            title=str(title),
            assignment_status=final_status,
        )

    def _sync_assignment_text_to_lexicon(
        self,
        *,
        assignment_id: int,
        content_completed: str,
        operation: str,
    ) -> None:
        target = self._assignment_sync_use_case
        if target is None:
            return
        content = str(content_completed or "")
        if not content.strip():
            return
        try:
            result = target.execute(
                text=content,
                sync=True,
                third_pass_enabled=True,
                think_mode=False,
            )
        except Exception as exc:
            self._log_error(operation=f"{operation}.sync_assignment_to_lexicon", error=exc)
            return

        if result.success:
            status = str(result.status_code or "ok")
            self._log_info(
                "assignment_sync_to_lexicon: "
                f"operation={operation}, id={assignment_id}, status={status}"
            )
            return

        self._log_info(
            "assignment_sync_to_lexicon: "
            f"operation={operation}, id={assignment_id}, status=failed, "
            f"error={str(result.error_message or '').strip() or 'unknown'}"
        )

    def _resolve_assignment_status(self, coverage_percent: float) -> str:
        if float(coverage_percent) >= self._completed_threshold_percent:
            return "COMPLETED"
        return "PENDING"

    def _extract_sentence(self, *, content: str, term: str) -> str:
        if self._sentence_extractor is None:
            return ""
        try:
            sentence = self._sentence_extractor.extract_sentence(
                text=str(content or ""),
                term=str(term or ""),
            )
        except Exception:
            return ""
        return str(sentence or "").strip()

    def _exists_in_category(self, *, term: str, category: str) -> bool:
        single_word, multi_word = self._lexicon_repository.build_index()
        if " " in term:
            key = tuple(item for item in term.split() if item)
            existing = {
                str(item).strip().casefold()
                for item in multi_word.get(key, [])
                if str(item).strip()
            }
            return str(category).strip().casefold() in existing
        existing = {
            str(item).strip().casefold()
            for item in single_word.get(term, [])
            if str(item).strip()
        }
        return str(category).strip().casefold() in existing

