from __future__ import annotations

from dataclasses import replace

from core.domain import (
    CategoryMutationResult,
    LexiconDeleteRequest,
    LexiconMutationResult,
    LexiconQuery,
    LexiconSearchResult,
    LexiconUpdateRequest,
    Result,
)
from core.domain import ICategoryRepository, ILexiconRepository, ILoggingService
from core.use_cases._base import BaseInteractor


def _is_category_mutation_failure(message: str) -> bool:
    text = str(message or "").strip().casefold()
    if not text:
        return False
    failure_markers = ("failed", "must not be empty", "skipped", "not found")
    return any(marker in text for marker in failure_markers)


class ManageLexiconInteractor(BaseInteractor):
    def __init__(
        self,
        *,
        lexicon_repository: ILexiconRepository,
        category_repository: ICategoryRepository,
        logger: ILoggingService | None = None,
    ) -> None:
        self._lexicon_repository = lexicon_repository
        self._category_repository = category_repository
        self._logger = logger

    def search(self, query: LexiconQuery) -> Result[LexiconSearchResult]:
        try:
            result = self._lexicon_repository.search_entries(query)
            self._log_info(
                "search_entries: "
                f"filtered={result.filtered_rows}, total={result.total_rows}, "
                f"status={result.status_filter}, category={result.category_filter}, "
                f"value={result.value_filter}, source={result.source_filter}, request={result.request_filter}, "
                f"id_min={result.id_min}, id_max={result.id_max}, "
                f"reviewed_by={result.reviewed_by_filter}, "
                f"confidence_min={result.confidence_min}, confidence_max={result.confidence_max}"
            )
            return Result.ok(result)
        except Exception as exc:
            self._log_error(operation="search_entries", error=exc)
            return Result.fail(f"Search failed: {exc}", status_code="search_exception")

    def update_entry(
        self,
        *,
        entry_id: int,
        status: str,
        category: str,
        value: str,
        query: LexiconQuery,
    ) -> Result[LexiconSearchResult]:
        try:
            mutation = self._lexicon_repository.update_entry(
                LexiconUpdateRequest(
                    entry_id=int(entry_id),
                    status=str(status),
                    category=str(category),
                    value=str(value),
                )
            )
            self._log_info(f"update_entry: id={entry_id}, success={mutation.success}, message={mutation.message}")
            result = self._lexicon_repository.search_entries(query)
            payload = self._search_with_message(result=result, mutation=mutation)
            if mutation.success:
                return Result.ok(payload)
            return Result.fail(mutation.message, status_code="update_failed", data=payload)
        except Exception as exc:
            self._log_error(operation="update_entry", error=exc)
            return Result.fail(f"Update failed: {exc}", status_code="update_exception")

    def bulk_update_status(
        self,
        *,
        entry_ids: list[int],
        status: str,
        query: LexiconQuery,
    ) -> Result[LexiconSearchResult]:
        updated = 0
        errors: list[str] = []
        for entry_id in entry_ids:
            try:
                current = self._lexicon_repository.get_entry(int(entry_id))
                if current is None:
                    errors.append(f"id={entry_id} not found")
                    continue
                mutation = self._lexicon_repository.update_entry(
                    LexiconUpdateRequest(
                        entry_id=current.id,
                        status=str(status),
                        category=str(current.category),
                        value=str(current.value),
                    )
                )
                if mutation.success:
                    updated += 1
                else:
                    errors.append(f"id={entry_id}: {mutation.message}")
            except Exception as exc:
                self._log_error(operation="bulk_update_status", error=exc)
                errors.append(f"id={entry_id}: {exc}")
        self._log_info(f"bulk_update_status: status={status}, updated={updated}, errors={len(errors)}")
        try:
            result = self._lexicon_repository.search_entries(query)
            message = f"Updated {updated} of {len(entry_ids)} entries to '{status}'."
            if errors:
                message += f" Errors: {len(errors)}."
            mutation_result = LexiconMutationResult(
                success=not errors,
                message=message,
                affected_count=updated,
            )
            payload = self._search_with_message(result=result, mutation=mutation_result)
            return Result.ok(payload) if not errors else Result.fail(message, status_code="bulk_update_partial", data=payload)
        except Exception as exc:
            self._log_error(operation="bulk_update_status_search", error=exc)
            return Result.fail(f"Bulk update failed: {exc}", status_code="bulk_update_exception")

    def assign_category(
        self,
        *,
        entry_id: int,
        category: str,
        query: LexiconQuery,
    ) -> Result[LexiconSearchResult]:
        try:
            current = self._lexicon_repository.get_entry(int(entry_id))
            if current is None:
                failure = LexiconMutationResult(
                    success=False,
                    message=f"Update skipped: entry id={int(entry_id)} not found.",
                    affected_count=0,
                )
                result = self._lexicon_repository.search_entries(query)
                payload = self._search_with_message(result=result, mutation=failure)
                return Result.fail(failure.message, status_code="assign_not_found", data=payload)

            return self.update_entry(
                entry_id=current.id,
                status=current.status,
                category=str(category),
                value=current.value,
                query=query,
            )
        except Exception as exc:
            self._log_error(operation="assign_category", error=exc)
            return Result.fail(f"Assign category failed: {exc}", status_code="assign_exception")

    def delete_entries(self, *, entry_ids: list[int], query: LexiconQuery) -> Result[LexiconSearchResult]:
        try:
            mutation = self._lexicon_repository.delete_entries(LexiconDeleteRequest(entry_ids=list(entry_ids)))
            self._log_info(
                f"delete_entries: ids={entry_ids}, success={mutation.success}, affected={mutation.affected_count}"
            )
            result = self._lexicon_repository.search_entries(query)
            payload = self._search_with_message(result=result, mutation=mutation)
            if mutation.success:
                return Result.ok(payload)
            return Result.fail(mutation.message, status_code="delete_failed", data=payload)
        except Exception as exc:
            self._log_error(operation="delete_entries", error=exc)
            return Result.fail(f"Delete failed: {exc}", status_code="delete_exception")

    def list_categories(self) -> Result[list[str]]:
        try:
            categories = self._category_repository.list_categories()
            self._log_info(f"list_categories: count={len(categories)}")
            return Result.ok(categories)
        except Exception as exc:
            self._log_error(operation="list_categories", error=exc)
            return Result.fail(f"List categories failed: {exc}", status_code="categories_exception")

    def create_category(self, name: str) -> Result[CategoryMutationResult]:
        try:
            result = self._category_repository.create_category(name)
            self._log_info(f"create_category: name={name}, message={result.message}")
            if _is_category_mutation_failure(result.message):
                return Result.fail(result.message, status_code="create_category_failed", data=result)
            return Result.ok(result)
        except Exception as exc:
            self._log_error(operation="create_category", error=exc)
            return Result.fail(f"Create category failed: {exc}", status_code="create_category_exception")

    def delete_category(self, name: str) -> Result[CategoryMutationResult]:
        try:
            result = self._category_repository.delete_category(name)
            self._log_info(f"delete_category: name={name}, message={result.message}")
            if _is_category_mutation_failure(result.message):
                return Result.fail(result.message, status_code="delete_category_failed", data=result)
            return Result.ok(result)
        except Exception as exc:
            self._log_error(operation="delete_category", error=exc)
            return Result.fail(f"Delete category failed: {exc}", status_code="delete_category_exception")

    def _search_with_message(
        self,
        *,
        result: LexiconSearchResult,
        mutation: LexiconMutationResult,
    ) -> LexiconSearchResult:
        return replace(result, message=mutation.message)



