from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from threading import RLock
import time
from types import MappingProxyType
from typing import Callable, Dict, Iterable

from .table_models import LexiconEntry
from .phrase_matcher import PhraseTrieMatcher
from .text_utils import TOKEN_PATTERN


@dataclass(frozen=True)
class LexiconIndexSnapshot:
    version: int
    single_word: MappingProxyType[str, tuple[str, ...]]
    multi_word: MappingProxyType[tuple[str, ...], tuple[str, ...]]
    phrase_matcher: PhraseTrieMatcher
    candidate_hash: str

    def as_legacy(self) -> tuple[dict[str, list[str]], dict[tuple[str, ...], list[str]]]:
        single = {key: list(value) for key, value in self.single_word.items()}
        multi = {key: list(value) for key, value in self.multi_word.items()}
        return single, multi


class LexiconIndexProvider:
    def __init__(
        self,
        *,
        entry_loader: Callable[[], list[LexiconEntry]],
        version_loader: Callable[[], int],
        rebuild_debounce_seconds: float = 0.0,
    ) -> None:
        self._entry_loader = entry_loader
        self._version_loader = version_loader
        self._lock = RLock()
        self._snapshot: LexiconIndexSnapshot | None = None
        self._rebuild_debounce_seconds = max(0.0, rebuild_debounce_seconds)
        self._last_rebuild_monotonic = 0.0
        self._pending_entries: list[LexiconEntry] = []
        self._pending_version: int | None = None

    def get_snapshot(self) -> tuple[LexiconIndexSnapshot, bool]:
        current_version = self._version_loader()
        with self._lock:
            self._maybe_apply_pending(now=time.monotonic(), force=False)
            if self._snapshot is not None and self._snapshot.version == current_version:
                return self._snapshot, True
            if (
                self._snapshot is not None
                and current_version != self._snapshot.version
                and not self._can_rebuild(now=time.monotonic())
            ):
                return self._snapshot, True
            entries = self._entry_loader()
            snapshot = self._build_snapshot(entries, current_version)
            self._snapshot = snapshot
            self._last_rebuild_monotonic = time.monotonic()
            return snapshot, False

    def invalidate(self) -> None:
        with self._lock:
            self._snapshot = None
            self._pending_entries.clear()
            self._pending_version = None

    def apply_entry(self, entry: LexiconEntry, *, new_version: int) -> None:
        with self._lock:
            if self._snapshot is None:
                return
            if self._rebuild_debounce_seconds <= 0.0:
                self._snapshot = self._apply_entries_to_snapshot(
                    self._snapshot,
                    [entry],
                    new_version=new_version,
                )
                return
            self._pending_entries.append(entry)
            self._pending_version = max(new_version, self._pending_version or new_version)
            self._maybe_apply_pending(now=time.monotonic(), force=False)

    def _can_rebuild(self, *, now: float) -> bool:
        if self._rebuild_debounce_seconds <= 0.0:
            return True
        return (now - self._last_rebuild_monotonic) >= self._rebuild_debounce_seconds

    def _maybe_apply_pending(self, *, now: float, force: bool) -> None:
        if self._snapshot is None or not self._pending_entries:
            return
        if not force and not self._can_rebuild(now=now):
            return
        new_version = self._pending_version if self._pending_version is not None else self._snapshot.version
        self._snapshot = self._apply_entries_to_snapshot(
            self._snapshot,
            self._pending_entries,
            new_version=new_version,
        )
        self._pending_entries = []
        self._pending_version = None
        self._last_rebuild_monotonic = now

    def _apply_entries_to_snapshot(
        self,
        snapshot: LexiconIndexSnapshot,
        entries: list[LexiconEntry],
        *,
        new_version: int,
    ) -> LexiconIndexSnapshot:
        single_word = {key: set(value) for key, value in snapshot.single_word.items()}
        multi_word = {key: set(value) for key, value in snapshot.multi_word.items()}

        for entry in entries:
            pieces = [token.lower() for token in TOKEN_PATTERN.findall(entry.value)]
            if not pieces:
                continue
            if len(pieces) == 1:
                single_word.setdefault(pieces[0], set()).add(entry.category)
            else:
                multi_word.setdefault(tuple(pieces), set()).add(entry.category)
        return self.snapshot_from_maps(single_word, multi_word, new_version)

    def _build_snapshot(self, entries: Iterable[LexiconEntry], version: int) -> LexiconIndexSnapshot:
        single_word: Dict[str, set[str]] = defaultdict(set)
        multi_word: Dict[tuple[str, ...], set[str]] = defaultdict(set)

        for entry in entries:
            pieces = [token.lower() for token in TOKEN_PATTERN.findall(entry.value)]
            if not pieces:
                continue
            if len(pieces) == 1:
                single_word[pieces[0]].add(entry.category)
            else:
                multi_word[tuple(pieces)].add(entry.category)
        return self.snapshot_from_maps(single_word, multi_word, version)

    def snapshot_from_maps(
        self,
        single_word: dict[str, set[str]],
        multi_word: dict[tuple[str, ...], set[str]],
        version: int,
    ) -> LexiconIndexSnapshot:
        single_sorted = {key: tuple(sorted(values)) for key, values in single_word.items()}
        multi_sorted = {key: tuple(sorted(values)) for key, values in multi_word.items()}
        phrase_matcher = PhraseTrieMatcher.from_phrases(multi_sorted)
        candidate_hash = self._candidate_hash(single_sorted.keys())
        return LexiconIndexSnapshot(
            version=version,
            single_word=MappingProxyType(single_sorted),
            multi_word=MappingProxyType(multi_sorted),
            phrase_matcher=phrase_matcher,
            candidate_hash=candidate_hash,
        )

    def _candidate_hash(self, candidates: Iterable[str]) -> str:
        joined = "\x1f".join(sorted(candidates))
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()
