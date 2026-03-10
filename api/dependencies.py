"""Dependency injection: use case singletons for FastAPI routes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.bootstrap.web_builder import WebComponents

_components: "WebComponents | None" = None
_executor: ThreadPoolExecutor | None = None


def init_dependencies(components: "WebComponents") -> None:
    global _components, _executor
    _components = components
    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="api_worker")


def shutdown_dependencies() -> None:
    global _components, _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None
    if _components is not None:
        try:
            _components.parse_use_case.close(timeout_seconds=5.0)
        except Exception:
            pass
        try:
            _components.llama_server_manager.close()
        except Exception:
            pass
        try:
            _components.assignment_store.close()
        except Exception:
            pass
        try:
            _components.sqlite_repository.close()
        except Exception:
            pass
        _components = None


def get_components() -> "WebComponents":
    if _components is None:
        raise RuntimeError("Dependencies not initialized")
    return _components


def get_executor() -> ThreadPoolExecutor:
    if _executor is None:
        raise RuntimeError("Executor not initialized")
    return _executor


# FastAPI Depends helpers
def dep_parse_use_case():
    return get_components().parse_use_case


def dep_manage_use_case():
    return get_components().manage_use_case


def dep_export_use_case():
    return get_components().export_use_case


def dep_assignments_use_case():
    return get_components().assignments_use_case


def dep_statistics_use_case():
    return get_components().statistics_use_case


def dep_coordinator():
    return get_components().initialization_coordinator
