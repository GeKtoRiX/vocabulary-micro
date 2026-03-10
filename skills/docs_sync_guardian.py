"""Проверка синхронизации policy-документов AGENTS.md и docs/agents.md."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_POLICY_MARKERS = (
    "validation_blocked_high_confidence_trf",
    "validation_suspicious_trf_uncertain",
    "validation_second_pass_empty_fallback",
    "validation_no_trf_signal_fallback",
    "validation_trf_not_uncertain",
)
REQUIRED_ASSIGNMENT_MARKERS = (
    "AssignmentSqliteStore",
    "assignments.db",
    "assignment_sync_use_case",
    "sync -> scan",
)
REQUIRED_SLA_MARKERS = (
    "p95 <= 1.2s",
    "p95 <= 200ms",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_latest_cycle(agents_text: str) -> int | None:
    matches = re.findall(r"Evolution Cycle\s+(\d+)", agents_text)
    if not matches:
        return None
    return max(int(item) for item in matches)


def _extract_docs_cycle(docs_text: str) -> int | None:
    match = re.search(r"Cycle\s+(\d+)", docs_text)
    if match is None:
        return None
    return int(match.group(1))


def audit_docs_sync(
    *,
    root_path: str | Path = ".",
    agents_path: str = "AGENTS.md",
    docs_agents_path: str = "docs/agents.md",
) -> dict[str, Any]:
    root = Path(root_path).resolve()
    agents_file = (root / agents_path).resolve()
    docs_file = (root / docs_agents_path).resolve()
    violations: list[str] = []

    if not agents_file.exists():
        violations.append(f"missing file: {agents_file}")
    if not docs_file.exists():
        violations.append(f"missing file: {docs_file}")
    if violations:
        return {
            "pass": False,
            "violations": violations,
            "agents_path": str(agents_file),
            "docs_agents_path": str(docs_file),
        }

    agents_text = _read_text(agents_file)
    docs_text = _read_text(docs_file)

    latest_cycle = _extract_latest_cycle(agents_text)
    docs_cycle = _extract_docs_cycle(docs_text)
    if latest_cycle is None:
        violations.append("failed to extract latest cycle from AGENTS.md changelog")
    if docs_cycle is None:
        violations.append("failed to extract cycle marker from docs/agents.md header")
    if latest_cycle is not None and docs_cycle is not None and docs_cycle != latest_cycle:
        violations.append(
            f"cycle mismatch: docs/agents.md=Cycle {docs_cycle}, AGENTS.md latest=Cycle {latest_cycle}"
        )

    for marker in REQUIRED_POLICY_MARKERS:
        if marker not in agents_text:
            violations.append(f"AGENTS.md missing policy marker: {marker}")
        if marker not in docs_text:
            violations.append(f"docs/agents.md missing policy marker: {marker}")

    for marker in REQUIRED_ASSIGNMENT_MARKERS:
        if marker not in agents_text:
            violations.append(f"AGENTS.md missing assignments marker: {marker}")
        if marker not in docs_text:
            violations.append(f"docs/agents.md missing assignments marker: {marker}")

    for marker in REQUIRED_SLA_MARKERS:
        if marker not in agents_text:
            violations.append(f"AGENTS.md missing SLA marker: {marker}")
        if marker not in docs_text:
            violations.append(f"docs/agents.md missing SLA marker: {marker}")

    return {
        "pass": len(violations) == 0,
        "violations": violations,
        "agents_path": str(agents_file),
        "docs_agents_path": str(docs_file),
        "latest_agents_cycle": latest_cycle,
        "docs_agents_cycle": docs_cycle,
        "checks": {
            "policy_markers": list(REQUIRED_POLICY_MARKERS),
            "assignment_markers": list(REQUIRED_ASSIGNMENT_MARKERS),
            "sla_markers": list(REQUIRED_SLA_MARKERS),
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Проверить синхронизацию AGENTS.md и docs/agents.md.")
    parser.add_argument("--root", default=".", help="Путь к корню репозитория.")
    parser.add_argument("--agents-path", default="AGENTS.md", help="Путь к AGENTS.md.")
    parser.add_argument("--docs-agents-path", default="docs/agents.md", help="Путь к docs/agents.md.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = audit_docs_sync(
        root_path=args.root,
        agents_path=args.agents_path,
        docs_agents_path=args.docs_agents_path,
    )
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
