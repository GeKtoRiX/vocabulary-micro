from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Iterable

from backend.python_services.core.domain import TokenRecord
from backend.python_services.infrastructure.config import PipelineSettings

from .text_utils import TOKEN_PATTERN, looks_like_weird_unicode, normalize_whitespace

try:
    import lemminflect  # noqa: F401
    from lemminflect import getAllInflections, getAllLemmas
except Exception:
    getAllInflections = None
    getAllLemmas = None


LEMMA_SKIP_WORDS = {
    "a",
    "an",
    "and",
    "or",
    "the",
    "this",
    "that",
    "these",
    "those",
}


class LemmaInflectMatcherStage:
    def __init__(self, settings: PipelineSettings) -> None:
        self._settings = settings
        self._global_cache: OrderedDict[str, tuple[str, ...]] = OrderedDict()
        self._cache_lock = RLock()

    @property
    def available(self) -> bool:
        if not self._settings.enable_lemminflect:
            return False
        return getAllLemmas is not None and getAllInflections is not None

    def apply(self, tokens: list[TokenRecord], single_word: dict[str, tuple[str, ...]]) -> dict[str, object]:
        unknown_tokens = [token for token in tokens if not token.known]
        if len(unknown_tokens) > self._settings.max_unknown_tokens_for_lemma_stage:
            return {
                "status": "skipped",
                "reason": "max_unknown_tokens_exceeded",
                "unknown_tokens": len(unknown_tokens),
                "matched_tokens": 0,
            }
        if not self.available:
            return {
                "status": "skipped",
                "reason": "lemminflect_unavailable",
                "unknown_tokens": len(unknown_tokens),
                "matched_tokens": 0,
            }

        request_cache: dict[str, tuple[str, ...]] = {}
        matched_tokens = 0
        for token in unknown_tokens:
            if self._skip_token(token):
                continue
            candidates = self._lemma_inflect_candidates(token, request_cache=request_cache)
            if not candidates:
                continue
            matched_categories: set[str] = set()
            matched_forms: list[str] = []
            for candidate in candidates:
                categories = single_word.get(candidate)
                if not categories:
                    continue
                matched_categories.update(categories)
                matched_forms.append(candidate)

            if not matched_categories:
                continue

            token.categories = sorted(matched_categories)
            token.known = True
            token.match_source = "lemma_inflect"
            token.matched_form = ", ".join(sorted(set(matched_forms)))
            matched_tokens += 1
        return {
            "status": "ok",
            "reason": "",
            "unknown_tokens": len(unknown_tokens),
            "matched_tokens": matched_tokens,
        }

    def _skip_token(self, token: TokenRecord) -> bool:
        value = token.normalized
        if not value:
            return True
        if len(value) < 2:
            return True
        if value in LEMMA_SKIP_WORDS:
            return True
        if value.isdigit():
            return True
        if looks_like_weird_unicode(value):
            return True
        if TOKEN_PATTERN.fullmatch(value) is None:
            return True
        return False

    def _lemma_inflect_candidates(
        self,
        token: TokenRecord,
        *,
        request_cache: dict[str, tuple[str, ...]],
    ) -> tuple[str, ...]:
        key = f"{token.token.lower()}|{token.lemma.lower()}|{token.normalized.lower()}"
        if key in request_cache:
            return request_cache[key]
        cached = self._cache_get(key)
        if cached is not None:
            request_cache[key] = cached
            return cached

        candidates: list[str] = [token.normalized, token.lemma]
        if getAllLemmas is not None:
            lemma_map = getAllLemmas(token.token)
            for forms in lemma_map.values():
                candidates.extend(forms)

        candidate_bases = self._unique_candidates(candidates)
        if getAllInflections is not None:
            for base in list(candidate_bases):
                inflections = getAllInflections(base)
                for forms in inflections.values():
                    candidate_bases.extend(forms)
                    if len(candidate_bases) >= self._settings.max_inflect_candidates_per_token:
                        break
                if len(candidate_bases) >= self._settings.max_inflect_candidates_per_token:
                    break
        result = tuple(
            self._unique_candidates(candidate_bases)[: self._settings.max_inflect_candidates_per_token]
        )
        request_cache[key] = result
        self._cache_put(key, result)
        return result

    def _unique_candidates(self, values: Iterable[str]) -> list[str]:
        seen = set()
        result: list[str] = []
        for item in values:
            normalized = normalize_whitespace(str(item)).lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _cache_get(self, key: str) -> tuple[str, ...] | None:
        with self._cache_lock:
            value = self._global_cache.get(key)
            if value is None:
                return None
            self._global_cache.move_to_end(key)
            return value

    def _cache_put(self, key: str, value: tuple[str, ...]) -> None:
        with self._cache_lock:
            self._global_cache[key] = value
            self._global_cache.move_to_end(key)
            while len(self._global_cache) > self._settings.lemma_cache_max_entries:
                self._global_cache.popitem(last=False)



