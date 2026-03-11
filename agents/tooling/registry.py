"""Repository-level tool registry with Pydantic input validation.

This module provides reusable audit and maintenance tools for Codex workflows.
Each tool has:
- A Pydantic model for input validation.
- A typed Python handler.
- A registry entry for dynamic execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import ast
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, field_validator


class JsonFormatter(logging.Formatter):
    """Format logging records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a log record to JSON.

        Args:
            record: The logging record created by the logger.

        Returns:
            A JSON string containing core record metadata.
        """
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def _configure_logger() -> logging.Logger:
    """Create a structured logger for tool execution.

    Args:
        None.

    Returns:
        A configured logger instance.
    """
    logger = logging.getLogger("codex.tools")
    if logger.handlers:
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


LOGGER = _configure_logger()


class InspectRepositoryInput(BaseModel):
    """Input model for repository structure inspection.

    Args:
        root_path: Repository root to inspect.
        max_files: Maximum number of files to return.
        include_tests: Include `tests/` files in output.
        exclude_prefixes: Relative directory prefixes to skip.
    """

    root_path: str = Field(default=".", description="Repository root path.")
    max_files: int = Field(default=2000, ge=1, le=100000, description="Maximum files to collect.")
    include_tests: bool = Field(default=True, description="Whether to include test files.")
    exclude_prefixes: list[str] = Field(
        default_factory=lambda: [
            ".git/",
            ".venv/",
            "__pycache__/",
            ".pytest_cache/",
            "nltk_data/",
        ],
        description="Relative path prefixes excluded from inventory.",
    )


def inspect_repository(args: InspectRepositoryInput) -> dict[str, Any]:
    """Collect a lightweight repository inventory.

    Args:
        args: Validated inspection arguments.

    Returns:
        A dictionary with file inventory and key project markers.
    """
    root = Path(args.root_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Root path not found: {root}")

    files: list[str] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(root).as_posix()
        parts = set(relative.split("/"))
        if "__pycache__" in parts:
            continue
        if any(relative.startswith(prefix) for prefix in args.exclude_prefixes):
            continue
        if not args.include_tests and relative.startswith("tests/"):
            continue
        files.append(relative)
        if len(files) >= args.max_files:
            break

    payload = {
        "root": str(root),
        "file_count": len(files),
        "files": files,
        "entrypoints": [p for p in ("main.py", "README.md", "requirements.txt") if (root / p).exists()],
        "has_core": (root / "core").exists() or (root / "backend" / "python_services" / "core").exists(),
        "has_infrastructure": (root / "infrastructure").exists() or (root / "backend" / "python_services" / "infrastructure").exists(),
        "has_python_core": (root / "backend" / "python_services" / "core").exists(),
        "has_python_infrastructure": (root / "backend" / "python_services" / "infrastructure").exists(),
        "has_ui": (root / "frontend").exists() or (root / "ui").exists(),
        "has_frontend": (root / "frontend").exists(),
        "has_tests": (root / "tests").exists(),
    }
    LOGGER.info("inspect_repository complete root=%s file_count=%s", root, len(files))
    return payload


class BoundaryAuditInput(BaseModel):
    """Input model for static import-boundary checks.

    Args:
        root_path: Repository root path.
        core_path: Relative path to the canonical core package.
        ui_path: Relative path to the frontend/UI package.
        forbidden_core_roots: Import roots forbidden in the core layer.
    """

    root_path: str = Field(default=".", description="Repository root path.")
    core_path: str = Field(
        default="backend/python_services/core",
        description="Relative canonical core directory.",
    )
    ui_path: str = Field(default="frontend", description="Relative frontend/ui directory.")
    forbidden_core_roots: list[str] = Field(
        default_factory=lambda: ["tkinter", "sqlite3", "pandas", "infrastructure", "ui", "frontend"],
        description="Top-level import roots forbidden in the core layer.",
    )


def _python_files(root: Path) -> list[Path]:
    """Return Python files under a root directory.

    Args:
        root: Directory to traverse.

    Returns:
        Sorted list of `.py` files.
    """
    if not root.exists():
        return []
    return sorted(root.rglob("*.py"))


def _imports_for_file(path: Path) -> list[tuple[str, int]]:
    """Extract import modules and line numbers from a Python file.

    Args:
        path: Python source file path.

    Returns:
        List of `(module_name, line_number)` tuples.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((str(alias.name), int(node.lineno)))
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            if module:
                imports.append((module, int(node.lineno)))
    return imports


def _is_forbidden_core_import(module_name: str, forbidden_roots: set[str]) -> bool:
    root_name = module_name.split(".", 1)[0]
    if root_name in forbidden_roots:
        return True
    return module_name.startswith("backend.python_services.infrastructure")


def _is_forbidden_ui_import(module_name: str) -> bool:
    root_name = module_name.split(".", 1)[0]
    if root_name == "infrastructure":
        return True
    return module_name.startswith("backend.python_services.infrastructure")


def audit_import_boundaries(args: BoundaryAuditInput) -> dict[str, Any]:
    """Audit canonical Python core/frontend import boundaries via static AST inspection.

    Args:
        args: Validated boundary-audit arguments.

    Returns:
        Dictionary containing violations and pass/fail flags.
    """
    root = Path(args.root_path).resolve()
    core_root = root / args.core_path
    ui_root = root / args.ui_path

    core_violations: list[str] = []
    ui_violations: list[str] = []

    forbidden = set(args.forbidden_core_roots)
    for file_path in _python_files(core_root):
        for module_name, line in _imports_for_file(file_path):
            if _is_forbidden_core_import(module_name, forbidden):
                rel = file_path.relative_to(root).as_posix()
                core_violations.append(f"{rel}:{line} imports {module_name}")

    for file_path in _python_files(ui_root):
        for module_name, line in _imports_for_file(file_path):
            if _is_forbidden_ui_import(module_name):
                rel = file_path.relative_to(root).as_posix()
                ui_violations.append(f"{rel}:{line} imports {module_name}")

    guardian_payload: dict[str, Any] = {}
    try:
        from skills.system_health_guardian import audit_ui_imports  # pylint: disable=import-outside-toplevel

        guardian_payload = audit_ui_imports(root_path=root, ui_path=args.ui_path)
        ui_violations.extend(str(item) for item in guardian_payload.get("violations", []))
    except Exception as exc:  # pragma: no cover - runtime fallback
        guardian_payload = {
            "pass": False,
            "violations": [f"system_health_guardian_failed: {exc}"],
            "scanned_files": 0,
        }
        ui_violations.extend(str(item) for item in guardian_payload["violations"])

    payload = {
        "core_pass": len(core_violations) == 0,
        "ui_pass": len(ui_violations) == 0,
        "core_violations": core_violations,
        "ui_violations": ui_violations,
        "ui_guardian_pass": bool(guardian_payload.get("pass", False)),
        "ui_guardian_violations": list(guardian_payload.get("violations", [])),
        "ui_guardian_scanned_files": int(guardian_payload.get("scanned_files", 0)),
    }
    LOGGER.info(
        "audit_import_boundaries complete core_pass=%s ui_pass=%s",
        payload["core_pass"],
        payload["ui_pass"],
    )
    return payload


class DocsSyncAuditInput(BaseModel):
    """Input model for AGENTS/docs synchronization checks."""

    root_path: str = Field(default=".", description="Repository root path.")
    agents_path: str = Field(default="AGENTS.md", description="AGENTS policy document path.")
    docs_agents_path: str = Field(
        default="docs/agents.md",
        description="Operator summary document path.",
    )


def audit_docs_sync(args: DocsSyncAuditInput) -> dict[str, Any]:
    """Audit AGENTS/docs policy synchronization."""
    from skills.docs_sync_guardian import audit_docs_sync as _audit_docs_sync

    payload = _audit_docs_sync(
        root_path=args.root_path,
        agents_path=args.agents_path,
        docs_agents_path=args.docs_agents_path,
    )
    LOGGER.info("audit_docs_sync complete pass=%s", bool(payload.get("pass", False)))
    return payload


class RunPytestInput(BaseModel):
    """Input model for running pytest from tool workflows.

    Args:
        root_path: Repository root path.
        target: Test path or expression to run.
        max_failures: Stop after this many failures.
        timeout_seconds: Subprocess timeout in seconds.
        quiet: Use pytest `-q` mode.
    """

    root_path: str = Field(default=".", description="Repository root path.")
    target: str = Field(default="tests", description="Pytest target path or expression.")
    max_failures: int = Field(default=1, ge=1, le=1000, description="Pytest --maxfail value.")
    timeout_seconds: int = Field(default=300, ge=10, le=7200, description="Command timeout.")
    quiet: bool = Field(default=True, description="Run pytest in quiet mode.")


def run_pytest(args: RunPytestInput) -> dict[str, Any]:
    """Run pytest in a subprocess and collect structured output.

    Args:
        args: Validated pytest execution arguments.

    Returns:
        Dictionary with return code, command, stdout, and stderr.
    """
    root = Path(args.root_path).resolve()
    command: list[str] = ["python", "-m", "pytest", args.target, f"--maxfail={args.max_failures}"]
    if args.quiet:
        command.append("-q")

    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=args.timeout_seconds,
        check=False,
    )
    duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
    payload = {
        "command": command,
        "cwd": str(root),
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "duration_ms": duration_ms,
    }
    LOGGER.info("run_pytest complete return_code=%s duration_ms=%s", completed.returncode, duration_ms)
    return payload


class NaturalLanguageQueryInput(BaseModel):
    """Input schema for natural-language SQLite queries.

    Args:
        query: Natural language intent/query string.
        context: Optional context payload (e.g., db_path, defaults).
        semantic_raw_query: Optional raw semantic intent text.
        action: Optional explicit action override.
        status: Optional status filter (`all|approved|pending_review|rejected`).
        limit: Optional result page size.
        offset: Optional result offset.
        category_filter: Optional category filter.
        value_filter: Optional value/term filter.
        source_filter: Optional source filter (`all|manual|auto`).
        request_filter: Optional request id filter.
        id_min: Optional lower bound for entry id.
        id_max: Optional upper bound for entry id.
        reviewed_by_filter: Optional reviewer name filter.
        confidence_min: Optional lower bound for confidence score.
        confidence_max: Optional upper bound for confidence score.
        sort_by: Optional sort column.
        sort_direction: Optional sort direction (`asc|desc`).
        db_path: Optional database path override.
    """

    query: str = Field(min_length=1, description="Natural language query text.")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional query context and execution hints.",
    )
    semantic_raw_query: str | None = Field(
        default=None,
        description="Optional raw semantic query text override.",
    )
    action: str | None = Field(
        default=None,
        description="Optional action override: search, count, list_categories.",
    )
    status: str | None = Field(default=None, description="Optional status filter.")
    limit: int | None = Field(default=None, ge=1, le=500, description="Optional query limit.")
    offset: int | None = Field(default=None, ge=0, description="Optional query offset.")
    category_filter: str | None = Field(default=None, description="Optional category filter.")
    value_filter: str | None = Field(default=None, description="Optional value filter.")
    source_filter: str | None = Field(default=None, description="Optional source filter.")
    request_filter: str | None = Field(default=None, description="Optional request filter.")
    id_min: int | None = Field(default=None, ge=1, description="Optional lower id bound.")
    id_max: int | None = Field(default=None, ge=1, description="Optional upper id bound.")
    reviewed_by_filter: str | None = Field(default=None, description="Optional reviewer filter.")
    confidence_min: float | None = Field(default=None, description="Optional lower confidence bound.")
    confidence_max: float | None = Field(default=None, description="Optional upper confidence bound.")
    sort_by: str | None = Field(default=None, description="Optional sort column.")
    sort_direction: str | None = Field(default=None, description="Optional sort direction.")
    db_path: str | None = Field(default=None, description="Optional SQLite DB path override.")

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("query must not be empty.")
        return cleaned


def natural_language_query(args: NaturalLanguageQueryInput) -> dict[str, Any]:
    """Execute a natural-language query via semantic bridge skill.

    Args:
        args: Validated natural-language query input.

    Returns:
        Structured execution payload from semantic query engine.
    """
    from skills.semantic_query_engine import execute_semantic_query

    merged_context = dict(args.context or {})
    explicit_fields = {
        "semantic_raw_query": args.semantic_raw_query,
        "action": args.action,
        "status": args.status,
        "limit": args.limit,
        "offset": args.offset,
        "category_filter": args.category_filter,
        "value_filter": args.value_filter,
        "source_filter": args.source_filter,
        "request_filter": args.request_filter,
        "id_min": args.id_min,
        "id_max": args.id_max,
        "reviewed_by_filter": args.reviewed_by_filter,
        "confidence_min": args.confidence_min,
        "confidence_max": args.confidence_max,
        "sort_by": args.sort_by,
        "sort_direction": args.sort_direction,
        "db_path": args.db_path,
    }
    for key, value in explicit_fields.items():
        if value is None:
            continue
        merged_context[key] = value

    LOGGER.info("natural_language_query execute query=%s", args.query)
    return execute_semantic_query(query=args.query, context=merged_context)


ToolInput = BaseModel
ToolHandler = Callable[[ToolInput], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    """Tool registry entry.

    Args:
        name: Stable tool identifier.
        model: Pydantic input model class.
        handler: Callable receiving validated model and returning payload.
        description: Human-readable description for discovery.
    """

    name: str
    model: type[BaseModel]
    handler: Callable[[BaseModel], dict[str, Any]]
    description: str


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "inspect_repository": ToolDefinition(
        name="inspect_repository",
        model=InspectRepositoryInput,
        handler=lambda payload: inspect_repository(payload),  # type: ignore[arg-type]
        description="Collect repository inventory and key markers.",
    ),
    "audit_import_boundaries": ToolDefinition(
        name="audit_import_boundaries",
        model=BoundaryAuditInput,
        handler=lambda payload: audit_import_boundaries(payload),  # type: ignore[arg-type]
        description="Validate import boundaries for canonical Python core/frontend layers.",
    ),
    "audit_docs_sync": ToolDefinition(
        name="audit_docs_sync",
        model=DocsSyncAuditInput,
        handler=lambda payload: audit_docs_sync(payload),  # type: ignore[arg-type]
        description="Validate AGENTS.md and docs/agents.md policy synchronization.",
    ),
    "run_pytest": ToolDefinition(
        name="run_pytest",
        model=RunPytestInput,
        handler=lambda payload: run_pytest(payload),  # type: ignore[arg-type]
        description="Execute pytest with bounded failure and timeout controls.",
    ),
    "NaturalLanguageQuery": ToolDefinition(
        name="NaturalLanguageQuery",
        model=NaturalLanguageQueryInput,
        handler=lambda payload: natural_language_query(payload),  # type: ignore[arg-type]
        description="Query lexicon SQL services using natural language intent.",
    ),
}


def list_tools() -> list[dict[str, str]]:
    """List available registry tools.

    Args:
        None.

    Returns:
        A list of tool metadata dictionaries.
    """
    return [
        {"name": item.name, "description": item.description, "model": item.model.__name__}
        for item in TOOL_REGISTRY.values()
    ]


def execute_tool(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate input and execute a registered tool.

    Args:
        name: Tool name from `TOOL_REGISTRY`.
        payload: Raw payload to validate with the tool's Pydantic model.

    Returns:
        Handler return payload.
    """
    definition = TOOL_REGISTRY.get(name)
    if definition is None:
        raise KeyError(f"Unknown tool: {name}")

    validated = definition.model.model_validate(payload or {})
    return definition.handler(validated)
