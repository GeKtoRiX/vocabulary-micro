from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.use_cases import ParseAndSyncInteractor
from infrastructure.adapters import HttpLexiconGateway
from infrastructure.bootstrap.initialization_coordinator import InitializationCoordinator
from infrastructure.bootstrap.llama_server_runtime import LlamaCppServerManager
from infrastructure.config import PipelineSettings
from infrastructure.logging import AppLoggingService


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _runtime_dir() -> Path:
    return _project_root() / "backend" / "python_services" / "infrastructure" / "runtime"


def _logs_dir() -> Path:
    path = _runtime_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _warmup_probe_db_path() -> Path:
    path = _runtime_dir() / "data" / "nlp_service_warmup.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _lexicon_service_base_url() -> str:
    import os

    explicit = str(os.getenv("LEXICON_SERVICE_BASE_URL", "")).strip()
    if explicit:
        return explicit.rstrip("/")
    host = str(os.getenv("LEXICON_SERVICE_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    port = str(os.getenv("LEXICON_SERVICE_PORT", "4011")).strip() or "4011"
    return f"http://{host}:{port}"


@dataclass
class NlpComponents:
    parse_use_case: ParseAndSyncInteractor
    lexicon_gateway: HttpLexiconGateway
    initialization_coordinator: InitializationCoordinator
    llama_server_manager: LlamaCppServerManager
    logger: AppLoggingService


def build_nlp_components() -> NlpComponents:
    project_root = _project_root()
    settings = PipelineSettings.from_env()
    logger = AppLoggingService(_logs_dir() / "nlp_service.log", logger_name="nlp_service")

    initialization_coordinator = InitializationCoordinator(
        project_root=project_root,
        db_path=_warmup_probe_db_path(),
    )
    initialization_coordinator.start()

    llama_server_manager = LlamaCppServerManager(
        settings=settings,
        project_root=project_root,
        logger=logger,
    )
    llama_server_manager.ensure_started()

    lexicon_gateway = HttpLexiconGateway(
        base_url=_lexicon_service_base_url(),
        settings=settings,
        third_pass_preflight=llama_server_manager.ensure_started,
    )
    parse_use_case = ParseAndSyncInteractor(
        repository=lexicon_gateway,
        category_repository=lexicon_gateway,
        logger=logger,
        source_label="lexicon-service",
        settings=settings.to_parse_sync_settings(),
    )
    return NlpComponents(
        parse_use_case=parse_use_case,
        lexicon_gateway=lexicon_gateway,
        initialization_coordinator=initialization_coordinator,
        llama_server_manager=llama_server_manager,
        logger=logger,
    )
