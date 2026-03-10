from __future__ import annotations

from pathlib import Path

import tools


ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_governance_files_exist_and_have_required_sections() -> None:
    required_files = (
        "AGENTS.md",
        "MEMORY.md",
        "CONTINUITY.md",
        "docs/agents.md",
    )
    for relative_path in required_files:
        assert (ROOT / relative_path).exists(), relative_path

    memory_text = _read("MEMORY.md")
    continuity_text = _read("CONTINUITY.md")

    for marker in (
        "## Overview",
        "## Architecture",
        "## Stack",
        "## Runtime/Services",
        "## Constraints",
        "## Commands",
        "## Decisions",
        "## Open Risks",
    ):
        assert marker in memory_text

    for marker in (
        "## Current Task",
        "## Progress",
        "## Blocked by",
        "## Next Step",
        "## Last Updated",
    ):
        assert marker in continuity_text


def test_docs_sync_audit_passes_for_bootstrap_documents() -> None:
    payload = tools.audit_docs_sync(
        tools.DocsSyncAuditInput(root_path=str(ROOT))
    )

    assert payload["pass"] is True, payload["violations"]
