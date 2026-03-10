from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LexiconEntry:
    row: int
    column: int
    category: str
    value: str
