from __future__ import annotations

from typing import Protocol


class ISentenceExtractor(Protocol):
    def extract_sentence(self, *, text: str, term: str) -> str: ...
