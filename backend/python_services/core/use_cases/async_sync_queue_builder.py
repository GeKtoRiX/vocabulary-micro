from __future__ import annotations

from typing import Callable

from core.domain import ILoggingService, ParseSyncSettings
from core.domain.services import AsyncSyncJob, AsyncSyncQueue, ISyncQueue

SyncQueueFactory = Callable[
    [Callable[[AsyncSyncJob], dict[str, object]], ParseSyncSettings, ILoggingService | None, str],
    ISyncQueue,
]


class AsyncSyncQueueBuilder:
    """Build async sync queue instances from settings and optional persistence factory."""

    def __init__(
        self,
        *,
        settings: ParseSyncSettings,
        logger: ILoggingService | None,
        source_label: str,
        sync_queue_factory: SyncQueueFactory | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._source_label = str(source_label).strip() or "lexicon"
        self._sync_queue_factory = sync_queue_factory

    @property
    def persistent_queue_enabled(self) -> bool:
        return bool(
            self._settings.async_sync_persistent_enabled and self._sync_queue_factory is not None
        )

    def build(
        self,
        *,
        handler: Callable[[AsyncSyncJob], dict[str, object]],
        log_info: Callable[[str], None] | None = None,
    ) -> ISyncQueue:
        if self._settings.async_sync_persistent_enabled:
            if self._sync_queue_factory is None:
                if log_info is not None:
                    log_info(
                        "async_sync_persistent_enabled=true but sync_queue_factory is not configured; "
                        "falling back to in-memory queue"
                    )
            else:
                return self._sync_queue_factory(
                    handler,
                    self._settings,
                    self._logger,
                    self._source_label,
                )
        return AsyncSyncQueue(
            handler=handler,
            max_size=self._settings.async_sync_queue_size,
            worker_count=self._settings.async_sync_worker_count,
            name="parse_sync_async_queue",
            logger=self._logger,
        )
