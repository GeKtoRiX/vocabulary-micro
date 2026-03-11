from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_ROOT = "backend/python_services/core"


def _python_files(relative_root: str) -> list[Path]:
    root = REPO_ROOT / relative_root
    if not root.exists():
        return []
    return sorted(root.rglob("*.py"))


def _imports_for_file(path: Path) -> list[tuple[str, int]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((str(alias.name), int(node.lineno)))
        elif isinstance(node, ast.ImportFrom):
            module_name = str(node.module or "")
            if module_name:
                imports.append((module_name, int(node.lineno)))
    return imports


def test_core_dependency_rule() -> None:
    violations: list[str] = []
    forbidden_roots = {"tkinter", "sqlite3", "pandas", "infrastructure", "ui", "frontend"}
    for file_path in _python_files(CORE_ROOT):
        for module_name, line in _imports_for_file(file_path):
            root_name = module_name.split(".", 1)[0]
            if root_name in forbidden_roots or module_name.startswith("backend.python_services.infrastructure"):
                relative = file_path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{relative}:{line} imports {module_name}")
    assert not violations, "backend/python_services/core violates dependency rule:\n" + "\n".join(violations)
