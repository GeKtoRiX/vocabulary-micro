"""Web bootstrap: builds all use cases without tkinter for the FastAPI web server."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.domain.services import AssignmentScannerService
from core.use_cases import (
    ExportLexiconInteractor,
    ManageAssignmentsInteractor,
    ManageLexiconInteractor,
    ParseAndSyncInteractor,
    StatisticsInteractor,
)
from infrastructure.adapters.assignment_gateway import AssignmentSqliteStore
from infrastructure.adapters.export_service import SqliteExcelExportService
from infrastructure.adapters.lexicon_gateway import SqliteLexiconGateway
from infrastructure.adapters.sync_queue_adapter import PersistentAsyncSyncQueue
from infrastructure.bootstrap.llama_server_runtime import LlamaCppServerManager
from infrastructure.bootstrap.startup_service import StartupContext, StartupService
from infrastructure.config import PipelineSettings
from infrastructure.logging import AppLoggingService
from infrastructure.sqlite import AssignmentSentenceExtractor
from .initialization_coordinator import InitializationCoordinator


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sync_queue_factory(
    *,
    context: StartupContext,
    handler: Callable[..., object],
    settings: PipelineSettings,
    queue_logger: AppLoggingService,
    source_label: str,
) -> PersistentAsyncSyncQueue:
    queue_path = Path(settings.async_sync_queue_db_path)
    if not queue_path.is_absolute():
        queue_path = context.db_path.resolve().parent / queue_path
    queue_name = (
        f"parse_sync_queue:{Path(source_label).name}"
        if source_label
        else "parse_sync_persistent_async_queue"
    )
    return PersistentAsyncSyncQueue(
        handler=handler,
        max_size=settings.async_sync_queue_size,
        db_path=queue_path,
        worker_count=settings.async_sync_worker_count,
        poll_interval_ms=settings.async_sync_poll_interval_ms,
        max_attempts=settings.async_sync_max_attempts,
        name=queue_name,
        logger=queue_logger,
    )


@dataclass
class WebComponents:
    parse_use_case: ParseAndSyncInteractor
    manage_use_case: ManageLexiconInteractor
    export_use_case: ExportLexiconInteractor
    assignments_use_case: ManageAssignmentsInteractor
    statistics_use_case: StatisticsInteractor
    initialization_coordinator: InitializationCoordinator
    llama_server_manager: LlamaCppServerManager
    logger: AppLoggingService
    context: StartupContext
    sqlite_repository: SqliteLexiconGateway
    assignment_store: AssignmentSqliteStore


def build_web_components() -> WebComponents:
    """Build all use cases and infrastructure for the web server, without tkinter."""
    startup_service = StartupService(project_root=_project_root())
    context = startup_service.initialize()

    logger = AppLoggingService(context.app_log_path)
    settings = PipelineSettings.from_env()

    initialization_coordinator = InitializationCoordinator(
        project_root=context.project_root,
        db_path=context.db_path,
    )
    initialization_coordinator.start()

    llama_server_manager = LlamaCppServerManager(
        settings=settings,
        project_root=context.project_root,
        logger=logger,
    )
    llama_server_manager.ensure_started()

    sqlite_repository = SqliteLexiconGateway(
        db_path=context.db_path,
        settings=settings,
        third_pass_preflight=llama_server_manager.ensure_started,
    )

    assignments_db_path = Path(settings.assignments_db_path)
    if not assignments_db_path.is_absolute():
        assignments_db_path = context.db_path.resolve().parent / assignments_db_path
    if assignments_db_path.resolve() == context.db_path.resolve():
        assignments_db_path = assignments_db_path.with_name("assignments.db")

    assignment_store = AssignmentSqliteStore(assignments_db_path)

    parse_use_case = ParseAndSyncInteractor(
        repository=sqlite_repository,
        category_repository=sqlite_repository,
        logger=logger,
        source_label=str(context.db_path.resolve()),
        sync_queue_factory=lambda handler, queue_settings, queue_logger, source_label: _sync_queue_factory(
            context=context,
            handler=handler,
            settings=queue_settings,
            queue_logger=queue_logger,
            source_label=source_label,
        ),
        settings=settings.to_parse_sync_settings(),
    )

    manage_use_case = ManageLexiconInteractor(
        lexicon_repository=sqlite_repository,
        category_repository=sqlite_repository,
        logger=logger,
    )

    assignment_scanner_service = AssignmentScannerService(
        lexicon_search_interactor=manage_use_case,
    )
    sentence_extractor = AssignmentSentenceExtractor(settings=settings)

    assignments_use_case = ManageAssignmentsInteractor(
        assignment_repository=assignment_store,
        scanner_service=assignment_scanner_service,
        lexicon_repository=sqlite_repository,
        completed_threshold_percent=settings.assignment_completed_threshold_percent,
        assignment_sync_use_case=parse_use_case,
        sentence_extractor=sentence_extractor,
        logger=logger,
    )

    export_service = SqliteExcelExportService(db_path=context.db_path)
    export_use_case = ExportLexiconInteractor(service=export_service, logger=logger)

    statistics_use_case = StatisticsInteractor(
        lexicon_repository=sqlite_repository,
        assignment_repository=assignment_store,
    )

    return WebComponents(
        parse_use_case=parse_use_case,
        manage_use_case=manage_use_case,
        export_use_case=export_use_case,
        assignments_use_case=assignments_use_case,
        statistics_use_case=statistics_use_case,
        initialization_coordinator=initialization_coordinator,
        llama_server_manager=llama_server_manager,
        logger=logger,
        context=context,
        sqlite_repository=sqlite_repository,
        assignment_store=assignment_store,
    )
