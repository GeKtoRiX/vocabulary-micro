"""Минимальный fallback для semantic query skill внутри репозитория."""

from __future__ import annotations

from typing import Any


def execute_semantic_query(*, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "message": "semantic_query_engine skill is not installed in this repository",
        "query": str(query),
        "context": dict(context or {}),
    }
