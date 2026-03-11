from __future__ import annotations

from dataclasses import dataclass, field
import os

from backend.python_services.infrastructure.config.env_readers import (
    read_bool as _read_bool,
    read_float as _read_float,
    read_int as _read_int,
    read_str as _read_str,
)


DEFAULT_BERT_BACKEND = "string_similarity"
DEFAULT_SECOND_PASS_BACKEND = "rule_based"


def _default_bert_model_name() -> str:
    return DEFAULT_BERT_BACKEND


def _default_local_files_only() -> bool:
    return True


def _default_st_model_name() -> str:
    return DEFAULT_SECOND_PASS_BACKEND


@dataclass(frozen=True)
class PipelineSettings:
    enable_bert: bool = True
    enable_lemminflect: bool = True
    enable_wordnet: bool = True
    auto_sync_enabled: bool = True
    async_sync_enabled: bool = False
    async_sync_persistent_enabled: bool = False
    async_sync_queue_size: int = 256
    async_sync_worker_count: int = 1
    async_sync_queue_db_path: str = "sync_queue.store"
    async_sync_max_attempts: int = 3
    async_sync_poll_interval_ms: int = 150
    bert_model_name: str = field(default_factory=_default_bert_model_name)
    bert_model_revision: str | None = None
    bert_local_files_only: bool = field(default_factory=_default_local_files_only)
    bert_out_of_process_enabled: bool = False
    bert_ipc_host: str = "127.0.0.1"
    bert_ipc_port: int = 42395
    bert_ipc_authkey: str = "lexicon_bert_ipc"
    bert_ipc_startup_timeout_ms: int = 5000
    bert_ipc_request_timeout_ms: int = 8000
    bert_threshold: float = 0.62
    bert_top_k: int = 400
    bert_batch_size: int = 64
    bert_device: str = "cpu"
    enable_bert_onnx: bool = False
    max_input_chars: int = 12_000
    max_input_tokens: int = 4_096
    max_request_bytes: int = 32_000
    request_timeout_ms: int = 8_000
    tokenize_timeout_ms: int = 2_500
    exact_match_timeout_ms: int = 800
    lemma_timeout_ms: int = 1_500
    wordnet_timeout_ms: int = 2_500
    bert_timeout_ms: int = 2_500
    sync_timeout_ms: int = 1_000
    max_inflect_candidates_per_token: int = 64
    max_unknown_tokens_for_lemma_stage: int = 512
    max_unknown_tokens_for_wordnet: int = 512
    max_unknown_tokens_for_bert: int = 128
    max_bert_candidates: int = 1_000
    index_rebuild_debounce_seconds: float = 0.0
    api_queue_max_size: int = 128
    api_reject_status_code: int = 503
    bert_circuit_breaker_failures: int = 3
    bert_circuit_breaker_reset_seconds: int = 300
    embedding_cache_max_entries: int = 8
    lemma_cache_max_entries: int = 2_048
    wordnet_cache_max_entries: int = 8_192
    enable_second_pass_wsd: bool = True
    trf_confidence_threshold: float = 0.8
    second_pass_top_n: int = 3
    second_pass_similarity_threshold: float = 0.52
    second_pass_margin_threshold: float = 0.08
    second_pass_max_gap_tokens: int = 4
    spacy_trf_model_name: str = "en_core_web_trf"
    st_model_name: str = field(default_factory=_default_st_model_name)
    st_model_revision: str | None = None
    st_local_files_only: bool = field(default_factory=_default_local_files_only)
    st_batch_size: int = 32
    enable_third_pass_llm: bool = False
    third_pass_llm_base_url: str = "http://127.0.0.1:1234"
    third_pass_llm_model: str = "llama3.1-8b-instruct"
    third_pass_llm_timeout_ms: int = 120_000
    third_pass_llm_max_tokens: int = 4_096
    third_pass_llm_max_items: int = 12
    third_pass_llm_think_mode: bool = False
    third_pass_llm_api_key: str | None = None
    llama_server_autostart_enabled: bool = False
    llama_server_executable: str = "backend/python_services/infrastructure/runtime/llama_cpp/bin/llama-server.exe"
    llama_server_model_path: str = ""
    llama_server_n_gpu_layers: int = -1
    llama_server_ctx_size: int = 8192
    llama_server_threads: int = 0
    llama_server_batch_size: int = 512
    llama_server_ubatch_size: int = 512
    llama_server_startup_timeout_ms: int = 90_000
    llama_server_rocm_library_dir: str = ""
    llama_server_parallel_slots: int = 1
    llama_server_flash_attn: str = "on"
    llama_server_cache_reuse: int = 256
    llama_server_disable_warmup: bool = True
    llama_server_disable_webui: bool = True
    llama_server_threads_batch: int = 0
    llama_server_threads_http: int = 8
    llama_server_extra_args: str = ""
    assignment_completed_threshold_percent: float = 90.0
    assignment_diff_viewer_enabled: bool = False

    @classmethod
    def from_env(cls) -> "PipelineSettings":
        return cls(
            enable_bert=_read_bool("ENABLE_BERT", True),
            enable_lemminflect=_read_bool("ENABLE_LEMMINFLECT", True),
            enable_wordnet=_read_bool("ENABLE_WORDNET", cls.enable_wordnet),
            auto_sync_enabled=_read_bool("AUTO_SYNC_ENABLED", True),
            async_sync_enabled=_read_bool("ASYNC_SYNC_ENABLED", cls.async_sync_enabled),
            async_sync_persistent_enabled=_read_bool(
                "ASYNC_SYNC_PERSISTENT_ENABLED",
                cls.async_sync_persistent_enabled,
            ),
            async_sync_queue_size=_read_int("ASYNC_SYNC_QUEUE_SIZE", cls.async_sync_queue_size),
            async_sync_worker_count=_read_int("ASYNC_SYNC_WORKER_COUNT", cls.async_sync_worker_count),
            async_sync_queue_db_path=_read_str("ASYNC_SYNC_QUEUE_DB_PATH", cls.async_sync_queue_db_path),
            async_sync_max_attempts=_read_int("ASYNC_SYNC_MAX_ATTEMPTS", cls.async_sync_max_attempts),
            async_sync_poll_interval_ms=_read_int(
                "ASYNC_SYNC_POLL_INTERVAL_MS",
                cls.async_sync_poll_interval_ms,
            ),
            bert_model_name=os.getenv("BERT_MODEL_NAME", _default_bert_model_name()),
            bert_model_revision=os.getenv("BERT_MODEL_REVISION"),
            bert_local_files_only=_read_bool("BERT_LOCAL_FILES_ONLY", _default_local_files_only()),
            bert_out_of_process_enabled=_read_bool(
                "BERT_OUT_OF_PROCESS_ENABLED",
                cls.bert_out_of_process_enabled,
            ),
            bert_ipc_host=_read_str("BERT_IPC_HOST", cls.bert_ipc_host),
            bert_ipc_port=_read_int("BERT_IPC_PORT", cls.bert_ipc_port),
            bert_ipc_authkey=_read_str("BERT_IPC_AUTHKEY", cls.bert_ipc_authkey),
            bert_ipc_startup_timeout_ms=_read_int(
                "BERT_IPC_STARTUP_TIMEOUT_MS",
                cls.bert_ipc_startup_timeout_ms,
            ),
            bert_ipc_request_timeout_ms=_read_int(
                "BERT_IPC_REQUEST_TIMEOUT_MS",
                cls.bert_ipc_request_timeout_ms,
            ),
            bert_threshold=_read_float("BERT_THRESHOLD", cls.bert_threshold),
            bert_top_k=_read_int("BERT_TOP_K", cls.bert_top_k),
            bert_batch_size=_read_int("BERT_BATCH_SIZE", cls.bert_batch_size),
            bert_device=os.getenv("BERT_DEVICE", cls.bert_device),
            enable_bert_onnx=_read_bool("ENABLE_BERT_ONNX", cls.enable_bert_onnx),
            max_input_chars=_read_int("MAX_INPUT_CHARS", cls.max_input_chars),
            max_input_tokens=_read_int("MAX_INPUT_TOKENS", cls.max_input_tokens),
            max_request_bytes=_read_int("MAX_REQUEST_BYTES", cls.max_request_bytes),
            request_timeout_ms=_read_int("REQUEST_TIMEOUT_MS", cls.request_timeout_ms),
            tokenize_timeout_ms=_read_int("TOKENIZE_TIMEOUT_MS", cls.tokenize_timeout_ms),
            exact_match_timeout_ms=_read_int("EXACT_TIMEOUT_MS", cls.exact_match_timeout_ms),
            lemma_timeout_ms=_read_int("LEMMA_TIMEOUT_MS", cls.lemma_timeout_ms),
            wordnet_timeout_ms=_read_int("WORDNET_TIMEOUT_MS", cls.wordnet_timeout_ms),
            bert_timeout_ms=_read_int("BERT_TIMEOUT_MS", cls.bert_timeout_ms),
            sync_timeout_ms=_read_int("SYNC_TIMEOUT_MS", cls.sync_timeout_ms),
            max_inflect_candidates_per_token=_read_int(
                "MAX_INFLECT_CANDIDATES_PER_TOKEN",
                cls.max_inflect_candidates_per_token,
            ),
            max_unknown_tokens_for_lemma_stage=_read_int(
                "MAX_UNKNOWN_TOKENS_FOR_LEMMA_STAGE",
                cls.max_unknown_tokens_for_lemma_stage,
            ),
            max_unknown_tokens_for_wordnet=_read_int(
                "MAX_UNKNOWN_TOKENS_FOR_WORDNET_STAGE",
                cls.max_unknown_tokens_for_wordnet,
            ),
            max_unknown_tokens_for_bert=_read_int(
                "MAX_UNKNOWN_TOKENS_FOR_BERT",
                cls.max_unknown_tokens_for_bert,
            ),
            max_bert_candidates=_read_int("MAX_BERT_CANDIDATES", cls.max_bert_candidates),
            index_rebuild_debounce_seconds=_read_float(
                "INDEX_REBUILD_DEBOUNCE_SECONDS",
                cls.index_rebuild_debounce_seconds,
            ),
            api_queue_max_size=_read_int("API_QUEUE_MAX_SIZE", cls.api_queue_max_size),
            api_reject_status_code=_read_int("API_REJECT_STATUS_CODE", cls.api_reject_status_code),
            bert_circuit_breaker_failures=_read_int(
                "BERT_CIRCUIT_BREAKER_FAILURES",
                cls.bert_circuit_breaker_failures,
            ),
            bert_circuit_breaker_reset_seconds=_read_int(
                "BERT_CIRCUIT_BREAKER_RESET_SECONDS",
                cls.bert_circuit_breaker_reset_seconds,
            ),
            embedding_cache_max_entries=_read_int(
                "EMBEDDING_CACHE_MAX_ENTRIES",
                cls.embedding_cache_max_entries,
            ),
            lemma_cache_max_entries=_read_int(
                "LEMMA_CACHE_MAX_ENTRIES",
                cls.lemma_cache_max_entries,
            ),
            wordnet_cache_max_entries=_read_int(
                "WORDNET_CACHE_MAX_ENTRIES",
                cls.wordnet_cache_max_entries,
            ),
            enable_second_pass_wsd=_read_bool("ENABLE_SECOND_PASS_WSD", cls.enable_second_pass_wsd),
            trf_confidence_threshold=_read_float(
                "TRF_CONFIDENCE_THRESHOLD",
                cls.trf_confidence_threshold,
            ),
            second_pass_top_n=_read_int("SECOND_PASS_TOP_N", cls.second_pass_top_n),
            second_pass_similarity_threshold=_read_float(
                "SECOND_PASS_SIMILARITY_THRESHOLD",
                cls.second_pass_similarity_threshold,
            ),
            second_pass_margin_threshold=_read_float(
                "SECOND_PASS_MARGIN_THRESHOLD",
                cls.second_pass_margin_threshold,
            ),
            second_pass_max_gap_tokens=_read_int(
                "SECOND_PASS_MAX_GAP_TOKENS",
                cls.second_pass_max_gap_tokens,
            ),
            spacy_trf_model_name=_read_str("SPACY_TRF_MODEL_NAME", cls.spacy_trf_model_name),
            st_model_name=_read_str("ST_MODEL_NAME", _default_st_model_name()),
            st_model_revision=os.getenv("ST_MODEL_REVISION"),
            st_local_files_only=_read_bool("ST_LOCAL_FILES_ONLY", _default_local_files_only()),
            st_batch_size=_read_int("ST_BATCH_SIZE", cls.st_batch_size),
            enable_third_pass_llm=_read_bool("ENABLE_THIRD_PASS_LLM", cls.enable_third_pass_llm),
            third_pass_llm_base_url=_read_str(
                "THIRD_PASS_LLM_BASE_URL",
                cls.third_pass_llm_base_url,
            ),
            third_pass_llm_model=_read_str(
                "THIRD_PASS_LLM_MODEL",
                cls.third_pass_llm_model,
            ),
            third_pass_llm_timeout_ms=_read_int(
                "THIRD_PASS_LLM_TIMEOUT_MS",
                cls.third_pass_llm_timeout_ms,
            ),
            third_pass_llm_max_tokens=_read_int(
                "THIRD_PASS_LLM_MAX_TOKENS",
                cls.third_pass_llm_max_tokens,
            ),
            third_pass_llm_max_items=_read_int(
                "THIRD_PASS_LLM_MAX_ITEMS",
                cls.third_pass_llm_max_items,
            ),
            third_pass_llm_think_mode=_read_bool(
                "THIRD_PASS_LLM_THINK_MODE",
                cls.third_pass_llm_think_mode,
            ),
            third_pass_llm_api_key=os.getenv("THIRD_PASS_LLM_API_KEY"),
            llama_server_autostart_enabled=_read_bool(
                "LLAMA_SERVER_AUTOSTART_ENABLED",
                cls.llama_server_autostart_enabled,
            ),
            llama_server_executable=_read_str(
                "LLAMA_SERVER_EXECUTABLE",
                cls.llama_server_executable,
            ),
            llama_server_model_path=_read_str(
                "LLAMA_SERVER_MODEL_PATH",
                cls.llama_server_model_path,
            ),
            llama_server_n_gpu_layers=_read_int(
                "LLAMA_SERVER_N_GPU_LAYERS",
                cls.llama_server_n_gpu_layers,
            ),
            llama_server_ctx_size=_read_int(
                "LLAMA_SERVER_CTX_SIZE",
                cls.llama_server_ctx_size,
            ),
            llama_server_threads=_read_int(
                "LLAMA_SERVER_THREADS",
                cls.llama_server_threads,
            ),
            llama_server_batch_size=_read_int(
                "LLAMA_SERVER_BATCH_SIZE",
                cls.llama_server_batch_size,
            ),
            llama_server_ubatch_size=_read_int(
                "LLAMA_SERVER_UBATCH_SIZE",
                cls.llama_server_ubatch_size,
            ),
            llama_server_startup_timeout_ms=_read_int(
                "LLAMA_SERVER_STARTUP_TIMEOUT_MS",
                cls.llama_server_startup_timeout_ms,
            ),
            llama_server_rocm_library_dir=_read_str(
                "LLAMA_SERVER_ROCM_LIBRARY_DIR",
                cls.llama_server_rocm_library_dir,
            ),
            llama_server_parallel_slots=_read_int(
                "LLAMA_SERVER_PARALLEL_SLOTS",
                cls.llama_server_parallel_slots,
            ),
            llama_server_flash_attn=_read_str(
                "LLAMA_SERVER_FLASH_ATTN",
                cls.llama_server_flash_attn,
            ),
            llama_server_cache_reuse=_read_int(
                "LLAMA_SERVER_CACHE_REUSE",
                cls.llama_server_cache_reuse,
            ),
            llama_server_disable_warmup=_read_bool(
                "LLAMA_SERVER_DISABLE_WARMUP",
                cls.llama_server_disable_warmup,
            ),
            llama_server_disable_webui=_read_bool(
                "LLAMA_SERVER_DISABLE_WEBUI",
                cls.llama_server_disable_webui,
            ),
            llama_server_threads_batch=_read_int(
                "LLAMA_SERVER_THREADS_BATCH",
                cls.llama_server_threads_batch,
            ),
            llama_server_threads_http=_read_int(
                "LLAMA_SERVER_THREADS_HTTP",
                cls.llama_server_threads_http,
            ),
            llama_server_extra_args=_read_str(
                "LLAMA_SERVER_EXTRA_ARGS",
                cls.llama_server_extra_args,
            ),
            assignment_completed_threshold_percent=_read_float(
                "ASSIGNMENT_COMPLETED_THRESHOLD_PERCENT",
                cls.assignment_completed_threshold_percent,
            ),
            assignment_diff_viewer_enabled=_read_bool(
                "ASSIGNMENT_DIFF_VIEWER_ENABLED",
                cls.assignment_diff_viewer_enabled,
            ),
        )

    def to_parse_sync_settings(self) -> "ParseSyncSettings":
        from backend.python_services.core.domain import ParseSyncSettings

        return ParseSyncSettings(
            auto_sync_enabled=self.auto_sync_enabled,
            enable_second_pass_wsd=self.enable_second_pass_wsd,
            enable_third_pass_llm=self.enable_third_pass_llm,
            trf_confidence_threshold=min(1.0, max(0.0, float(self.trf_confidence_threshold))),
            second_pass_top_n=max(1, self.second_pass_top_n),
            second_pass_max_gap_tokens=max(1, self.second_pass_max_gap_tokens),
            sync_timeout_ms=max(1, self.sync_timeout_ms),
            async_sync_enabled=self.async_sync_enabled,
            async_sync_queue_size=max(1, self.async_sync_queue_size),
            async_sync_worker_count=max(1, self.async_sync_worker_count),
            async_sync_queue_db_path=self.async_sync_queue_db_path,
            async_sync_max_attempts=max(1, self.async_sync_max_attempts),
            async_sync_poll_interval_ms=max(10, self.async_sync_poll_interval_ms),
            api_reject_status_code=self.api_reject_status_code,
            async_sync_persistent_enabled=self.async_sync_persistent_enabled,
            pipeline_build=_read_str("PIPELINE_BUILD", "dev-local").strip() or "dev-local",
        )
