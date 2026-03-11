from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import tools


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_inspect_repository_filters_files_and_reports_markers(tmp_path: Path) -> None:
    _write(tmp_path / "main.py", "print('ok')\n")
    _write(tmp_path / "README.md", "# Repo\n")
    _write(tmp_path / "backend" / "python_services" / "core" / "service.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_sample.py", "def test_x():\n    assert True\n")
    _write(tmp_path / ".venv" / "skip.py", "SHOULD_NOT_BE_LISTED = True\n")

    payload = tools.inspect_repository(
        tools.InspectRepositoryInput(
            root_path=str(tmp_path),
            include_tests=False,
            max_files=100,
        )
    )

    assert payload["root"] == str(tmp_path.resolve())
    assert payload["has_core"] is True
    assert payload["has_python_core"] is True
    assert payload["has_tests"] is True
    assert "main.py" in payload["entrypoints"]
    assert "README.md" in payload["entrypoints"]
    assert "backend/python_services/core/service.py" in payload["files"]
    assert "tests/test_sample.py" not in payload["files"]
    assert ".venv/skip.py" not in payload["files"]


def test_inspect_repository_raises_for_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-root"
    with pytest.raises(FileNotFoundError):
        tools.inspect_repository(tools.InspectRepositoryInput(root_path=str(missing)))


def test_audit_import_boundaries_reports_core_and_ui_violations(tmp_path: Path) -> None:
    _write(tmp_path / "backend" / "python_services" / "core" / "bad.py", "import sqlite3\n")
    _write(tmp_path / "frontend" / "bad.py", "import backend.python_services.infrastructure.logging\n")

    payload = tools.audit_import_boundaries(
        tools.BoundaryAuditInput(root_path=str(tmp_path))
    )

    assert payload["core_pass"] is False
    assert payload["ui_pass"] is False
    assert any("backend/python_services/core/bad.py" in item for item in payload["core_violations"])
    assert any("frontend/bad.py" in item for item in payload["ui_violations"])
    assert payload["ui_guardian_pass"] in {True, False}


def test_audit_import_boundaries_falls_back_when_guardian_import_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path / "backend" / "python_services" / "core" / "ok.py", "import math\n")
    _write(tmp_path / "frontend" / "ok.py", "import tkinter as tk\n")

    real_import = builtins.__import__

    def _failing_import(name: str, *args: object, **kwargs: object):
        if name == "skills.system_health_guardian":
            raise RuntimeError("guardian unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    payload = tools.audit_import_boundaries(
        tools.BoundaryAuditInput(root_path=str(tmp_path))
    )

    assert payload["core_pass"] is True
    assert payload["ui_guardian_pass"] is False
    assert any("system_health_guardian_failed" in item for item in payload["ui_violations"])


def test_run_pytest_builds_command_and_collects_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_run(
        command: list[str],
        *,
        cwd: str,
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
    ) -> SimpleNamespace:
        captured["command"] = command
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["check"] = check
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    counter = iter((10.0, 10.25))
    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    monkeypatch.setattr(tools.time, "perf_counter", lambda: next(counter))

    payload = tools.run_pytest(
        tools.RunPytestInput(
            root_path=".",
            target="tests/skills",
            max_failures=2,
            timeout_seconds=60,
            quiet=False,
        )
    )

    assert captured["command"] == [
        "python",
        "-m",
        "pytest",
        "tests/skills",
        "--maxfail=2",
    ]
    assert captured["timeout"] == 60
    assert payload["return_code"] == 0
    assert payload["stdout"] == "ok"
    assert payload["duration_ms"] == pytest.approx(250.0)


def test_natural_language_query_merges_context_and_explicit_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import skills.semantic_query_engine as semantic_query_engine

    captured: dict[str, object] = {}

    def _fake_execute_semantic_query(*, query: str, context: dict[str, object] | None = None) -> dict[str, object]:
        captured["query"] = query
        captured["context"] = dict(context or {})
        return {"success": True}

    monkeypatch.setattr(semantic_query_engine, "execute_semantic_query", _fake_execute_semantic_query)

    payload = tools.natural_language_query(
        tools.NaturalLanguageQueryInput(
            query="show entries",
            context={"status": "all", "limit": 100, "request_filter": "ctx-1"},
            status="approved",
            limit=7,
            source_filter="manual",
        )
    )

    assert payload == {"success": True}
    assert captured["query"] == "show entries"
    assert captured["context"] == {
        "status": "approved",
        "limit": 7,
        "request_filter": "ctx-1",
        "source_filter": "manual",
    }


def test_list_tools_and_execute_tool_behaviors() -> None:
    tool_names = {item["name"] for item in tools.list_tools()}
    assert {"inspect_repository", "audit_import_boundaries", "audit_docs_sync", "run_pytest", "NaturalLanguageQuery"} <= tool_names

    with pytest.raises(KeyError):
        tools.execute_tool("unknown_tool")


def test_execute_tool_validates_payload() -> None:
    with pytest.raises(ValidationError):
        tools.execute_tool("inspect_repository", {"max_files": 0})
