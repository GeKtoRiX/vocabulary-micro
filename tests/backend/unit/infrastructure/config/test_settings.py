from __future__ import annotations

import os

import pytest

from core.domain import ParseSyncSettings
from infrastructure.config.settings import PipelineSettings


def test_pipeline_settings_from_env_reads_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_BERT", "0")
    monkeypatch.setenv("ASYNC_SYNC_QUEUE_SIZE", "512")
    monkeypatch.setenv("SECOND_PASS_TOP_N", "5")
    monkeypatch.setenv("TRF_CONFIDENCE_THRESHOLD", "0.81")
    monkeypatch.setenv("SPACY_TRF_MODEL_NAME", "custom_trf")
    monkeypatch.setenv("ASSIGNMENT_COMPLETED_THRESHOLD_PERCENT", "87.5")
    monkeypatch.setenv("ASSIGNMENT_DIFF_VIEWER_ENABLED", "1")

    settings = PipelineSettings.from_env()
    assert settings.enable_bert is False
    assert settings.async_sync_queue_size == 512
    assert settings.second_pass_top_n == 5
    assert settings.trf_confidence_threshold == pytest.approx(0.81)
    assert settings.spacy_trf_model_name == "custom_trf"
    assert settings.assignment_completed_threshold_percent == pytest.approx(87.5)
    assert settings.assignment_diff_viewer_enabled is True


def test_pipeline_settings_to_parse_sync_settings_clamps_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_BUILD", "   ")

    settings = PipelineSettings(
        auto_sync_enabled=True,
        enable_second_pass_wsd=False,
        enable_third_pass_llm=True,
        trf_confidence_threshold=1.7,
        second_pass_top_n=0,
        second_pass_max_gap_tokens=0,
        sync_timeout_ms=0,
        async_sync_enabled=True,
        async_sync_queue_size=0,
        async_sync_worker_count=0,
        async_sync_queue_db_path="sync.sqlite3",
        async_sync_max_attempts=0,
        async_sync_poll_interval_ms=1,
        api_reject_status_code=429,
        async_sync_persistent_enabled=True,
    )

    parse_sync_settings = settings.to_parse_sync_settings()
    assert isinstance(parse_sync_settings, ParseSyncSettings)
    assert parse_sync_settings.second_pass_top_n == 1
    assert parse_sync_settings.second_pass_max_gap_tokens == 1
    assert parse_sync_settings.trf_confidence_threshold == pytest.approx(1.0)
    assert parse_sync_settings.sync_timeout_ms == 1
    assert parse_sync_settings.async_sync_queue_size == 1
    assert parse_sync_settings.async_sync_worker_count == 1
    assert parse_sync_settings.async_sync_max_attempts == 1
    assert parse_sync_settings.async_sync_poll_interval_ms == 10
    assert parse_sync_settings.pipeline_build == "dev-local"


def test_pipeline_settings_default_factories() -> None:
    assert PipelineSettings().bert_model_name == "string_similarity"
    assert PipelineSettings().st_model_name == "rule_based"
    assert PipelineSettings().bert_local_files_only is True
    assert PipelineSettings().st_local_files_only is True
    assert PipelineSettings().assignment_diff_viewer_enabled is False


def test_pipeline_settings_reads_llama_server_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLAMA_SERVER_AUTOSTART_ENABLED", "1")
    monkeypatch.setenv("LLAMA_SERVER_EXECUTABLE", "tools/llama/llama-server.exe")
    monkeypatch.setenv("LLAMA_SERVER_MODEL_PATH", "models/llama.gguf")
    monkeypatch.setenv("LLAMA_SERVER_N_GPU_LAYERS", "-1")
    monkeypatch.setenv("LLAMA_SERVER_CTX_SIZE", "4096")
    monkeypatch.setenv("LLAMA_SERVER_THREADS", "8")
    monkeypatch.setenv("LLAMA_SERVER_BATCH_SIZE", "256")
    monkeypatch.setenv("LLAMA_SERVER_UBATCH_SIZE", "128")
    monkeypatch.setenv("LLAMA_SERVER_STARTUP_TIMEOUT_MS", "65000")
    monkeypatch.setenv("LLAMA_SERVER_ROCM_LIBRARY_DIR", "tools/llama")
    monkeypatch.setenv("LLAMA_SERVER_PARALLEL_SLOTS", "1")
    monkeypatch.setenv("LLAMA_SERVER_FLASH_ATTN", "on")
    monkeypatch.setenv("LLAMA_SERVER_CACHE_REUSE", "256")
    monkeypatch.setenv("LLAMA_SERVER_DISABLE_WARMUP", "1")
    monkeypatch.setenv("LLAMA_SERVER_DISABLE_WEBUI", "1")
    monkeypatch.setenv("LLAMA_SERVER_THREADS_BATCH", "8")
    monkeypatch.setenv("LLAMA_SERVER_THREADS_HTTP", "8")
    monkeypatch.setenv("LLAMA_SERVER_EXTRA_ARGS", "--no-mmap --no-warmup")

    settings = PipelineSettings.from_env()
    assert settings.llama_server_autostart_enabled is True
    assert settings.llama_server_executable == "tools/llama/llama-server.exe"
    assert settings.llama_server_model_path == "models/llama.gguf"
    assert settings.llama_server_n_gpu_layers == -1
    assert settings.llama_server_ctx_size == 4096
    assert settings.llama_server_threads == 8
    assert settings.llama_server_batch_size == 256
    assert settings.llama_server_ubatch_size == 128
    assert settings.llama_server_startup_timeout_ms == 65000
    assert settings.llama_server_rocm_library_dir == "tools/llama"
    assert settings.llama_server_parallel_slots == 1
    assert settings.llama_server_flash_attn == "on"
    assert settings.llama_server_cache_reuse == 256
    assert settings.llama_server_disable_warmup is True
    assert settings.llama_server_disable_webui is True
    assert settings.llama_server_threads_batch == 8
    assert settings.llama_server_threads_http == 8
    assert settings.llama_server_extra_args == "--no-mmap --no-warmup"
