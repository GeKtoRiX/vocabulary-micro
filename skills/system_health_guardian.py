"""Аудит нежелательных импортов в UI-слое через статический AST-анализ."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def audit_ui_imports(*, root_path: str | Path, ui_path: str = "ui") -> dict[str, Any]:
    """Проверить файлы UI-слоя на запрещённые импорты из infrastructure.

    Args:
        root_path: Корень репозитория.
        ui_path: Относительный путь к UI-пакету.

    Returns:
        Словарь с ключами pass, violations, scanned_files.
    """
    root = Path(root_path).resolve()
    ui_root = root / ui_path
    violations: list[str] = []
    scanned = 0

    if not ui_root.exists():
        return {"pass": True, "violations": [], "scanned_files": 0}

    for file_path in sorted(ui_root.rglob("*.py")):
        scanned += 1
        source = file_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            violations.append(f"{file_path.relative_to(root).as_posix()}: syntax error")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] == "infrastructure":
                        rel = file_path.relative_to(root).as_posix()
                        violations.append(f"{rel}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".", 1)[0] == "infrastructure":
                    rel = file_path.relative_to(root).as_posix()
                    violations.append(f"{rel}:{node.lineno} imports {module}")

    return {"pass": len(violations) == 0, "violations": violations, "scanned_files": scanned}
