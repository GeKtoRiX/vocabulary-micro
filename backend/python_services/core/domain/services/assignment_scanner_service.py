from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
import re
import time
from typing import Protocol

from backend.python_services.core.domain import (
    AssignmentDiffChunk,
    AssignmentLexiconMatch,
    AssignmentMissingWord,
    AssignmentScanResultDTO,
    LexiconEntryRecord,
    LexiconQuery,
    LexiconSearchResult,
    Result,
)
from backend.python_services.core.domain.services.text_processor import DEFAULT_TEXT_PROCESSOR


TOKEN_PATTERN = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)?")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
DEFAULT_KNOWN_STATUSES = ("approved", "pending_review")
ALLOWED_KNOWN_STATUSES = {"approved", "pending_review", "rejected"}


class LexiconSearchPort(Protocol):
    def search(self, query: LexiconQuery) -> Result[LexiconSearchResult]: ...


class AssignmentScannerService:
    def __init__(
        self,
        *,
        lexicon_search_interactor: LexiconSearchPort,
        known_statuses: tuple[str, ...] | None = None,
        search_limit: int = 12000,
    ) -> None:
        self._lexicon_search_interactor = lexicon_search_interactor
        self._known_statuses = self._normalize_known_statuses(known_statuses)
        self._query_status = "all" if len(self._known_statuses) > 1 else self._known_statuses[0]
        self._search_limit = max(100, int(search_limit))

    def scan(
        self,
        *,
        content_completed: str,
        content_original: str = "",
        title: str = "",
    ) -> AssignmentScanResultDTO:
        started = time.perf_counter()
        completed_text = str(content_completed or "")
        completed_tokens = self._tokenize(completed_text)
        completed_normalized_tokens = self._normalize_tokens(completed_tokens)
        original_tokens = self._tokenize(content_original)
        lexicon_result = self._search_lexicon()
        lexicon_rows: list[LexiconEntryRecord] = []
        message = "Assignment scan completed."
        if lexicon_result.success and lexicon_result.data is not None:
            lexicon_rows = self._filter_known_rows(list(lexicon_result.data.rows))
        else:
            message = str(lexicon_result.error_message or "Assignment scan completed with lexicon fallback.")

        matches = self._match_terms(rows=lexicon_rows, completed_tokens=completed_normalized_tokens)
        known_mask = self._build_known_mask(rows=lexicon_rows, completed_tokens=completed_normalized_tokens)
        known_token_count = int(sum(1 for flag in known_mask if flag))
        total_tokens = len(completed_normalized_tokens)
        unknown_token_count = max(0, total_tokens - known_token_count)
        coverage_percent = 0.0
        if total_tokens > 0:
            coverage_percent = round((known_token_count / total_tokens) * 100.0, 2)
        missing_words = self._collect_missing_words(
            completed_text=completed_text,
            completed_tokens=completed_normalized_tokens,
            known_mask=known_mask,
        )
        diff_chunks = self._build_diff_chunks(
            original_tokens=original_tokens,
            completed_tokens=completed_tokens,
        )
        duration_ms = (time.perf_counter() - started) * 1000.0
        return AssignmentScanResultDTO(
            assignment_id=None,
            title=str(title or "").strip(),
            content_original=str(content_original or ""),
            content_completed=str(content_completed or ""),
            word_count=len(completed_normalized_tokens),
            matches=matches,
            diff_chunks=diff_chunks,
            duration_ms=round(duration_ms, 3),
            message=message,
            missing_words=missing_words,
            known_token_count=known_token_count,
            unknown_token_count=unknown_token_count,
            lexicon_coverage_percent=coverage_percent,
        )

    def _search_lexicon(self) -> Result[LexiconSearchResult]:
        return self._lexicon_search_interactor.search(
            LexiconQuery(
                status=self._query_status,
                limit=self._search_limit,
                offset=0,
                sort_by="id",
                sort_direction="desc",
            )
        )

    def _normalize_known_statuses(self, known_statuses: tuple[str, ...] | None) -> tuple[str, ...]:
        source = DEFAULT_KNOWN_STATUSES if known_statuses is None else known_statuses
        normalized: list[str] = []
        for raw in source:
            value = str(raw or "").strip().lower()
            if value not in ALLOWED_KNOWN_STATUSES:
                continue
            if value in normalized:
                continue
            normalized.append(value)
        if not normalized:
            return DEFAULT_KNOWN_STATUSES
        return tuple(normalized)

    def _filter_known_rows(self, rows: list[LexiconEntryRecord]) -> list[LexiconEntryRecord]:
        allowed = set(self._known_statuses)
        if not allowed:
            return []
        output: list[LexiconEntryRecord] = []
        for row in rows:
            status = str(row.status or "").strip().lower()
            if status in allowed:
                output.append(row)
        return output

    def _tokenize(self, content: str) -> list[str]:
        return [item.casefold() for item in TOKEN_PATTERN.findall(str(content or ""))]

    def _normalize_tokens(self, tokens: list[str]) -> list[str]:
        normalized_tokens: list[str] = []
        for token in tokens:
            normalized = DEFAULT_TEXT_PROCESSOR.normalize_lexeme(token)
            normalized_tokens.append(normalized or token)
        return normalized_tokens

    def _match_terms(
        self,
        *,
        rows: list[LexiconEntryRecord],
        completed_tokens: list[str],
    ) -> list[AssignmentLexiconMatch]:
        if not rows or not completed_tokens:
            return []

        term_rows: dict[str, list[LexiconEntryRecord]] = defaultdict(list)
        max_term_length = 1
        for row in rows:
            normalized = str(row.normalized or "").strip().casefold()
            if not normalized:
                continue
            term_rows[normalized].append(row)
            term_length = len(normalized.split())
            if term_length > max_term_length:
                max_term_length = term_length

        max_term_length = max(1, min(max_term_length, 6))
        ngram_counters = self._build_ngram_counters(
            tokens=completed_tokens,
            max_length=max_term_length,
        )
        matches: list[AssignmentLexiconMatch] = []
        for term, mapped_rows in term_rows.items():
            term_length = len(term.split())
            occurrences = int(ngram_counters.get(term_length, Counter()).get(term, 0))
            if occurrences <= 0:
                continue
            for row in mapped_rows:
                matches.append(
                    AssignmentLexiconMatch(
                        entry_id=int(row.id),
                        term=term,
                        category=str(row.category),
                        source=str(row.source),
                        occurrences=occurrences,
                    )
                )
        matches.sort(
            key=lambda item: (
                -int(item.occurrences),
                str(item.term),
                str(item.category),
                int(item.entry_id),
            )
        )
        return matches

    def _build_ngram_counters(self, *, tokens: list[str], max_length: int) -> dict[int, Counter[str]]:
        counters: dict[int, Counter[str]] = {}
        token_count = len(tokens)
        if token_count <= 0:
            return counters
        for size in range(1, max_length + 1):
            limit = token_count - size + 1
            if limit <= 0:
                break
            counters[size] = Counter(" ".join(tokens[index : index + size]) for index in range(limit))
        return counters

    def _build_known_mask(
        self,
        *,
        rows: list[LexiconEntryRecord],
        completed_tokens: list[str],
    ) -> list[bool]:
        token_count = len(completed_tokens)
        if token_count <= 0 or not rows:
            return [False] * token_count
        terms: set[tuple[str, ...]] = set()
        max_length = 1
        for row in rows:
            normalized = str(row.normalized or "").strip().casefold()
            if not normalized:
                continue
            parts = tuple(item for item in normalized.split() if item)
            if not parts:
                continue
            terms.add(parts)
            max_length = max(max_length, len(parts))
        max_length = max(1, min(max_length, 6))
        known_mask = [False] * token_count
        index = 0
        while index < token_count:
            best_size = 0
            max_size = min(max_length, token_count - index)
            for size in range(max_size, 0, -1):
                candidate = tuple(completed_tokens[index : index + size])
                if candidate in terms:
                    best_size = size
                    break
            if best_size <= 0:
                index += 1
                continue
            for mark in range(index, index + best_size):
                known_mask[mark] = True
            index += best_size
        return known_mask

    def _collect_missing_words(
        self,
        *,
        completed_text: str,
        completed_tokens: list[str],
        known_mask: list[bool],
    ) -> list[AssignmentMissingWord]:
        if not completed_tokens:
            return []
        unknown_counter: Counter[str] = Counter()
        for token, is_known in zip(completed_tokens, known_mask):
            if is_known:
                continue
            if len(token) < 2:
                continue
            unknown_counter[token] += 1
        if not unknown_counter:
            return []
        results: list[AssignmentMissingWord] = []
        for term, occurrences in sorted(
            unknown_counter.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        ):
            results.append(
                AssignmentMissingWord(
                    term=str(term),
                    occurrences=int(occurrences),
                    example_usage=self._find_sentence_for_term(completed_text=completed_text, term=term),
                )
            )
        return results

    def _find_sentence_for_term(self, *, completed_text: str, term: str) -> str:
        text = str(completed_text or "").strip()
        if not text:
            return ""
        target = str(term or "").strip()
        if not target:
            return ""
        lowered_target = target.casefold()
        for sentence in SENTENCE_SPLIT_PATTERN.split(text):
            clean = str(sentence or "").strip()
            if not clean:
                continue
            if lowered_target in clean.casefold():
                return clean
        return ""

    def _build_diff_chunks(
        self,
        *,
        original_tokens: list[str],
        completed_tokens: list[str],
    ) -> list[AssignmentDiffChunk]:
        matcher = SequenceMatcher(None, original_tokens, completed_tokens, autojunk=False)
        chunks: list[AssignmentDiffChunk] = []
        for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
            original_text = " ".join(original_tokens[i1:i2]).strip()
            completed_text = " ".join(completed_tokens[j1:j2]).strip()
            chunks.append(
                AssignmentDiffChunk(
                    operation=str(opcode),
                    original_text=original_text,
                    completed_text=completed_text,
                )
            )
        return chunks


__all__ = ["AssignmentScannerService", "LexiconSearchPort"]
