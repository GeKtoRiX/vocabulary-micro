from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Sequence


@dataclass
class _TrieNode:
    children: Dict[str, "_TrieNode"] = field(default_factory=dict)
    categories: tuple[str, ...] | None = None


class PhraseTrieMatcher:
    def __init__(self) -> None:
        self._root = _TrieNode()
        self._max_phrase_len = 1

    @property
    def max_phrase_len(self) -> int:
        return self._max_phrase_len

    def add_phrase(self, phrase_tokens: Sequence[str], categories: Sequence[str]) -> None:
        if len(phrase_tokens) < 2:
            return
        node = self._root
        for token in phrase_tokens:
            node = node.children.setdefault(token, _TrieNode())
        node.categories = tuple(sorted(set(categories)))
        self._max_phrase_len = max(self._max_phrase_len, len(phrase_tokens))

    @classmethod
    def from_phrases(
        cls,
        phrases: Dict[tuple[str, ...], Sequence[str]],
    ) -> "PhraseTrieMatcher":
        matcher = cls()
        for phrase_tokens, categories in phrases.items():
            matcher.add_phrase(phrase_tokens, categories)
        return matcher

    def longest_matches(self, normalized_tokens: Sequence[str]) -> list[tuple[int, int, tuple[str, ...], str]]:
        matches: list[tuple[int, int, tuple[str, ...], str]] = []
        token_count = len(normalized_tokens)
        for start in range(token_count):
            node = self._root
            best_end = -1
            best_categories: tuple[str, ...] | None = None
            end = start
            while end < token_count:
                token = normalized_tokens[end]
                next_node = node.children.get(token)
                if next_node is None:
                    break
                node = next_node
                if node.categories:
                    best_end = end
                    best_categories = node.categories
                end += 1
            if best_categories is None:
                continue
            normalized = " ".join(normalized_tokens[start : best_end + 1])
            matches.append((start, best_end, best_categories, normalized))
        return matches

    def iter_phrases(self) -> Iterable[tuple[tuple[str, ...], tuple[str, ...]]]:
        stack: list[tuple[tuple[str, ...], _TrieNode]] = [(tuple(), self._root)]
        while stack:
            prefix, node = stack.pop()
            if node.categories and len(prefix) >= 2:
                yield prefix, node.categories
            for token, child in node.children.items():
                stack.append((prefix + (token,), child))
