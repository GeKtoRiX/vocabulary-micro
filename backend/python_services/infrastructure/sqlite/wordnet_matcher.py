from __future__ import annotations

from collections import OrderedDict
import os
from pathlib import Path
from threading import RLock

from core.domain import TokenRecord
from infrastructure.config import PipelineSettings

from .text_utils import TOKEN_PATTERN, looks_like_weird_unicode

try:
    import nltk
    from nltk.corpus import wordnet as wn
except Exception:
    nltk = None
    wn = None


WORDNET_SKIP_WORDS = {
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


PROJECT_NLTK_DATA_DIR = Path(__file__).resolve().parents[2] / "nltk_data"


class WordNetMatcherStage:
    def __init__(self, settings: PipelineSettings) -> None:
        self._settings = settings
        self._available_checked = False
        self._available = False
        self._unavailable_reason: str | None = None
        self._omw_checked = False
        self._omw_available = False
        self._omw_unavailable_reason: str | None = None
        self._cache: OrderedDict[str, bool] = OrderedDict()
        self._cache_lock = RLock()

    @property
    def available(self) -> bool:
        return self._ensure_available()

    @property
    def unavailable_reason(self) -> str | None:
        self._ensure_available()
        return self._unavailable_reason

    @property
    def omw_available(self) -> bool:
        self._ensure_available()
        return bool(self._omw_available)

    @property
    def omw_unavailable_reason(self) -> str | None:
        self._ensure_available()
        return self._omw_unavailable_reason

    def apply(self, tokens: list[TokenRecord]) -> dict[str, object]:
        unknown_tokens = [token for token in tokens if not token.known]
        self._ensure_available()
        availability = self._availability_payload()

        if len(unknown_tokens) > self._settings.max_unknown_tokens_for_wordnet:
            return {
                "status": "skipped",
                "reason": "max_unknown_tokens_exceeded",
                "unknown_tokens": len(unknown_tokens),
                **availability,
            }

        if not self._available:
            return {
                "status": "skipped",
                "reason": self._unavailable_reason or "wordnet_unavailable",
                "unknown_tokens": len(unknown_tokens),
                **availability,
            }

        matched_tokens = 0
        for token in unknown_tokens:
            if self._skip_token(token):
                continue
            probe_forms = self._build_probe_forms(token)
            matched_form = ""
            for form in probe_forms:
                if self._has_wordnet_entry(form):
                    matched_form = form
                    break
            if not matched_form:
                continue
            token.known = True
            token.match_source = "wordnet"
            token.matched_form = matched_form
            matched_tokens += 1
        return {
            "status": "ok",
            "reason": "",
            "unknown_tokens": len(unknown_tokens),
            "matched_tokens": matched_tokens,
            **availability,
        }

    def _ensure_available(self) -> bool:
        if self._available_checked:
            return self._available
        self._available_checked = True

        if not self._settings.enable_wordnet:
            self._available = False
            self._unavailable_reason = "wordnet_disabled"
            self._set_omw_state(available=False, reason="wordnet_disabled")
            return False

        if nltk is None or wn is None:
            self._available = False
            self._unavailable_reason = "nltk_unavailable"
            self._set_omw_state(available=False, reason="nltk_unavailable")
            return False

        self._configure_local_nltk_data()
        try:
            wn.ensure_loaded()
            self._available = True
            self._unavailable_reason = ""
            self._ensure_omw_available()
        except LookupError:
            self._available = False
            self._unavailable_reason = "wordnet_corpus_missing"
            self._set_omw_state(available=False, reason="wordnet_corpus_missing")
        except Exception:
            self._available = False
            self._unavailable_reason = "wordnet_load_failed"
            self._set_omw_state(available=False, reason="wordnet_load_failed")
        return self._available

    def _ensure_omw_available(self) -> bool:
        if self._omw_checked:
            return self._omw_available
        self._omw_checked = True

        if nltk is None:
            self._omw_available = False
            self._omw_unavailable_reason = "nltk_unavailable"
            return False

        try:
            nltk.data.find("corpora/omw-1.4")
            self._omw_available = True
            self._omw_unavailable_reason = ""
            return True
        except LookupError:
            pass
        except Exception:
            self._omw_available = False
            self._omw_unavailable_reason = "omw_check_failed"
            return False

        try:
            nltk.data.find("corpora/omw")
            self._omw_available = True
            self._omw_unavailable_reason = ""
            return True
        except LookupError:
            self._omw_available = False
            self._omw_unavailable_reason = "omw_corpus_missing"
        except Exception:
            self._omw_available = False
            self._omw_unavailable_reason = "omw_check_failed"
        return self._omw_available

    def _set_omw_state(self, *, available: bool, reason: str) -> None:
        self._omw_checked = True
        self._omw_available = bool(available)
        self._omw_unavailable_reason = "" if available else str(reason)

    def _availability_payload(self) -> dict[str, object]:
        return {
            "wordnet_available": bool(self._available),
            "wordnet_unavailable_reason": str(self._unavailable_reason or ""),
            "omw_available": bool(self._omw_available),
            "omw_unavailable_reason": str(self._omw_unavailable_reason or ""),
        }

    def _configure_local_nltk_data(self) -> None:
        if nltk is None:
            return

        local_path = str(PROJECT_NLTK_DATA_DIR.resolve())
        env_paths_raw = str(os.getenv("NLTK_DATA", "")).strip()
        env_paths = [item.strip() for item in env_paths_raw.split(os.pathsep) if item.strip()]
        runtime_paths = [str(item).strip() for item in getattr(nltk.data, "path", []) if str(item).strip()]
        merged_paths = [local_path, *env_paths, *runtime_paths]

        unique_paths: list[str] = []
        seen: set[str] = set()
        for path_value in merged_paths:
            normalized = os.path.normcase(os.path.abspath(path_value))
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_paths.append(path_value)

        os.environ["NLTK_DATA"] = os.pathsep.join(unique_paths)
        nltk.data.path = list(unique_paths)

    def _skip_token(self, token: TokenRecord) -> bool:
        value = token.normalized
        if not value:
            return True
        if len(value) < 2:
            return True
        if value in WORDNET_SKIP_WORDS:
            return True
        if value.isdigit():
            return True
        if looks_like_weird_unicode(value):
            return True
        if TOKEN_PATTERN.fullmatch(value) is None:
            return True
        return False

    def _build_probe_forms(self, token: TokenRecord) -> tuple[str, ...]:
        forms = [token.lemma.lower().strip(), token.normalized.lower().strip()]
        unique: list[str] = []
        seen: set[str] = set()
        for form in forms:
            if not form or form in seen:
                continue
            seen.add(form)
            unique.append(form)
        return tuple(unique)

    def _has_wordnet_entry(self, value: str) -> bool:
        cached = self._cache_get(value)
        if cached is not None:
            return cached
        exists = self._wordnet_lookup(value)
        self._cache_put(value, exists)
        return exists

    def _wordnet_lookup(self, value: str) -> bool:
        if wn is None:
            return False
        try:
            if wn.synsets(value):
                return True
            lemma_form = wn.morphy(value)
            if lemma_form and wn.synsets(lemma_form):
                return True
        except Exception:
            return False
        return False

    def _cache_get(self, key: str) -> bool | None:
        with self._cache_lock:
            value = self._cache.get(key)
            if value is None:
                return None
            self._cache.move_to_end(key)
            return value

    def _cache_put(self, key: str, value: bool) -> None:
        with self._cache_lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._settings.wordnet_cache_max_entries:
                self._cache.popitem(last=False)

