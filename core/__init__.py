from __future__ import annotations

from pathlib import Path


_PACKAGE_DIR = Path(__file__).resolve().parent
_CANONICAL_DIR = _PACKAGE_DIR.parent / "backend" / "python_services" / "core"

__path__ = [str(_CANONICAL_DIR), str(_PACKAGE_DIR)]
__all__: list[str] = []
