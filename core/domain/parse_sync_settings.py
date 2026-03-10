from __future__ import annotations

from dataclasses import dataclass


DEFAULT_PIPELINE_BUILD = "dev-local"


@dataclass(frozen=True)
class ParseSyncSettings:
    auto_sync_enabled: bool = True
    enable_second_pass_wsd: bool = True
    enable_third_pass_llm: bool = False
    trf_confidence_threshold: float = 0.8
    second_pass_top_n: int = 3
    second_pass_max_gap_tokens: int = 4
    sync_timeout_ms: int = 1_000
    async_sync_enabled: bool = False
    async_sync_queue_size: int = 256
    async_sync_worker_count: int = 1
    async_sync_queue_db_path: str = "sync_queue.sqlite3"
    async_sync_max_attempts: int = 3
    async_sync_poll_interval_ms: int = 150
    api_reject_status_code: int = 503
    async_sync_persistent_enabled: bool = False
    pipeline_build: str = DEFAULT_PIPELINE_BUILD
