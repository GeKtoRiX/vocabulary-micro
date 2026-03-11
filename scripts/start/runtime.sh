initialize_start_state() {
  BUILD_FRONTEND=false
  DEV_MODE=false
  RESTART_MODE=true
  SERVICES_READY=false
  POSTGRES_MODE=0
  PRINT_CONFIG=false
  EXTRA_ENV_FILE="${START_ENV_FILE:-}"
  START_POSTGRES_VIA_COMPOSE="${START_POSTGRES_VIA_COMPOSE:-}"
  POSTGRES_DSN_HOST=""
  POSTGRES_DSN_PORT=""
  POSTGRES_STARTED_BY_SCRIPT=0
  FRONTEND_DEV_HOST="${FRONTEND_DEV_HOST:-127.0.0.1}"
  FRONTEND_DEV_PORT="${FRONTEND_DEV_PORT:-5173}"
  STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-90}"
  CLEANUP_RAN=0

  PYTHON_BACKEND="${PYTHON_BACKEND:-}"
  PYTHON_IMAGE_GPU="${PYTHON_IMAGE_GPU:-vocabulary-python-runtime-rocm:local}"
  PYTHON_IMAGE_CPU="${PYTHON_IMAGE_CPU:-vocabulary-python-runtime:local}"
  PYTHON_IMAGE=""
  ROCM_DOCKER_GPU_FLAGS=""
  PYTHON_DOCKER_GPU_FLAGS=""

  LLM_SERVICE_ENABLED="${LLM_SERVICE_ENABLED-}"
  LLM_SERVICE_RUNTIME="${LLM_SERVICE_RUNTIME-}"
  LLM_SERVICE_MODEL="${LLM_SERVICE_MODEL-}"
  LLM_SERVICE_HOST="${LLM_SERVICE_HOST-}"
  LLM_SERVICE_PORT="${LLM_SERVICE_PORT-}"
  LLM_SERVICE_MAX_MODEL_LEN="${LLM_SERVICE_MAX_MODEL_LEN-}"
  LLM_SERVICE_GPU_UTIL="${LLM_SERVICE_GPU_UTIL-}"
  LLM_SERVICE_READY_TIMEOUT_SECONDS="${LLM_SERVICE_READY_TIMEOUT_SECONDS-}"
  THIRD_PASS_LLM_TIMEOUT_MS="${THIRD_PASS_LLM_TIMEOUT_MS-}"
  LLM_SERVICE_EXECUTABLE="${LLM_SERVICE_EXECUTABLE-}"
  LLM_SERVICE_MODEL_PATH="${LLM_SERVICE_MODEL_PATH-}"
  LLM_SERVICE_N_GPU_LAYERS="${LLM_SERVICE_N_GPU_LAYERS-}"
  LLM_SERVICE_THREADS="${LLM_SERVICE_THREADS-}"
  LLM_SERVICE_BATCH_SIZE="${LLM_SERVICE_BATCH_SIZE-}"
  LLM_SERVICE_UBATCH_SIZE="${LLM_SERVICE_UBATCH_SIZE-}"
  LLM_SERVICE_THREADS_BATCH="${LLM_SERVICE_THREADS_BATCH-}"
  LLM_SERVICE_THREADS_HTTP="${LLM_SERVICE_THREADS_HTTP-}"
  LLM_SERVICE_PARALLEL_SLOTS="${LLM_SERVICE_PARALLEL_SLOTS-}"
  LLM_SERVICE_FLASH_ATTN="${LLM_SERVICE_FLASH_ATTN-}"
  LLM_SERVICE_CACHE_REUSE="${LLM_SERVICE_CACHE_REUSE-}"
  LLM_SERVICE_DISABLE_WARMUP="${LLM_SERVICE_DISABLE_WARMUP-}"
  LLM_SERVICE_DISABLE_WEBUI="${LLM_SERVICE_DISABLE_WEBUI-}"
  LLM_SERVICE_EXTRA_ARGS="${LLM_SERVICE_EXTRA_ARGS-}"
  VLLM_IMAGE="${VLLM_IMAGE-}"
  HF_CACHE="${HF_CACHE-}"

  PIDS=()
  PROCESS_GROUPS=()
  SERVICE_NAMES=()
  COMPOSE_CMD=()
}

print_start_usage() {
  cat <<EOF
Usage: $0 [--build] [--dev] [--no-restart] [--postgres] [--print-config]
  --build         Build frontend before starting server
  --dev           Start Vite dev server instead of serving built files
  --no-restart    Fail instead of killing existing processes on managed ports
  --postgres      Run owner services on Postgres using OWNER_SERVICES_* defaults
                  and auto-start local docker compose postgres for localhost DSN
  --print-config  Print resolved runtime config and exit

Environment variables:
  PYTHON_BACKEND=docker|native  Force Python service backend.
    docker  — run NLP/export services in Docker container (recommended).
              Auto-selected when Docker image is present.
    native  — run with host python3 (legacy; requires ML deps installed globally).
  PYTHON_IMAGE_GPU  Docker image for GPU (ROCm) mode (default: vocabulary-python-runtime-rocm:local).
  PYTHON_IMAGE_CPU  Docker image for CPU mode (default: vocabulary-python-runtime:local).
  BERT_DEVICE=cpu|cuda  GPU inference (requires ROCm image and AMD GPU).
  LLM_SERVICE_ENABLED=true|false  Start managed third-pass LLM service.
  LLM_SERVICE_RUNTIME=llama_cpp|vllm  Managed LLM runtime (default: llama_cpp).
  LLM_SERVICE_MODEL  Public model alias exposed to NLP (default: Qwen3.5-9B-GGUF).
  LLM_SERVICE_PORT  Local port for managed vLLM service (default: 8000).
  LLM_SERVICE_MAX_MODEL_LEN  Context length for managed LLM service (default: 8192).
  LLM_SERVICE_READY_TIMEOUT_SECONDS  Seconds to wait for managed LLM readiness (default: 900).
  THIRD_PASS_LLM_TIMEOUT_MS  Timeout for NLP -> LLM third-pass requests.
  GATEWAY_JOB_TTL_MS  TTL for long-running SSE jobs in api-gateway.
  LLM_SERVICE_EXECUTABLE  llama-server binary path or command (default: llama-server).
  LLM_SERVICE_MODEL_PATH  Local GGUF path for llama.cpp runtime.
  LLM_SERVICE_N_GPU_LAYERS  llama.cpp GPU layers (-1 = full offload).
  VLLM_IMAGE  ROCm vLLM image when LLM_SERVICE_RUNTIME=vllm (default: vllm/vllm-openai-rocm:latest).

First-time setup:
  ./scripts/prepare_docker_runtime.sh        # CPU image
  ./scripts/prepare_docker_runtime.sh --rocm # + GPU (ROCm) image (~3 GB)
  docker pull vllm/vllm-openai-rocm:latest   # managed vLLM image (only for LLM_SERVICE_RUNTIME=vllm)
EOF
}

parse_start_args() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      --build) BUILD_FRONTEND=true ;;
      --dev) DEV_MODE=true ;;
      --restart) RESTART_MODE=true ;;
      --no-restart) RESTART_MODE=false ;;
      --postgres) POSTGRES_MODE=1 ;;
      --print-config) PRINT_CONFIG=true ;;
      --help)
        print_start_usage
        exit 0
        ;;
    esac
  done
}

load_start_env_files() {
  load_env_defaults_file "$SCRIPT_DIR/.env"
  load_env_defaults_file "$SCRIPT_DIR/.env.local"
  if [ -n "$EXTRA_ENV_FILE" ]; then
    [[ "$EXTRA_ENV_FILE" != /* ]] && EXTRA_ENV_FILE="$SCRIPT_DIR/$EXTRA_ENV_FILE"
    load_env_defaults_file "$EXTRA_ENV_FILE"
  fi
  if [ "$POSTGRES_MODE" = "1" ] || [ "${POSTGRES_MODE:-0}" = "1" ]; then
    POSTGRES_MODE=1
    load_env_defaults_file "$SCRIPT_DIR/.env.postgres"
    load_env_defaults_file "$SCRIPT_DIR/.env.postgres.local"
  fi
  POSTGRES_MODE="${POSTGRES_MODE:-0}"
}

apply_runtime_defaults() {
  LLM_SERVICE_ENABLED="${LLM_SERVICE_ENABLED:-false}"
  LLM_SERVICE_RUNTIME="${LLM_SERVICE_RUNTIME:-llama_cpp}"
  LLM_SERVICE_MODEL="${LLM_SERVICE_MODEL:-Qwen3.5-9B-GGUF}"
  LLM_SERVICE_HOST="${LLM_SERVICE_HOST:-127.0.0.1}"
  LLM_SERVICE_PORT="${LLM_SERVICE_PORT:-8000}"
  LLM_SERVICE_MAX_MODEL_LEN="${LLM_SERVICE_MAX_MODEL_LEN:-8192}"
  LLM_SERVICE_GPU_UTIL="${LLM_SERVICE_GPU_UTIL:-0.90}"
  LLM_SERVICE_READY_TIMEOUT_SECONDS="${LLM_SERVICE_READY_TIMEOUT_SECONDS:-900}"
  if [ -z "${THIRD_PASS_LLM_TIMEOUT_MS:-}" ]; then
    [ "${LLM_SERVICE_RUNTIME}" = "llama_cpp" ] && THIRD_PASS_LLM_TIMEOUT_MS="240000" || THIRD_PASS_LLM_TIMEOUT_MS="30000"
  fi
  LLM_SERVICE_EXECUTABLE="${LLM_SERVICE_EXECUTABLE:-llama-server}"
  LLM_SERVICE_MODEL_PATH="${LLM_SERVICE_MODEL_PATH:-}"
  LLM_SERVICE_N_GPU_LAYERS="${LLM_SERVICE_N_GPU_LAYERS:--1}"
  LLM_SERVICE_THREADS="${LLM_SERVICE_THREADS:-0}"
  LLM_SERVICE_BATCH_SIZE="${LLM_SERVICE_BATCH_SIZE:-512}"
  LLM_SERVICE_UBATCH_SIZE="${LLM_SERVICE_UBATCH_SIZE:-512}"
  LLM_SERVICE_THREADS_BATCH="${LLM_SERVICE_THREADS_BATCH:-0}"
  LLM_SERVICE_THREADS_HTTP="${LLM_SERVICE_THREADS_HTTP:-8}"
  LLM_SERVICE_PARALLEL_SLOTS="${LLM_SERVICE_PARALLEL_SLOTS:-1}"
  LLM_SERVICE_FLASH_ATTN="${LLM_SERVICE_FLASH_ATTN:-on}"
  LLM_SERVICE_CACHE_REUSE="${LLM_SERVICE_CACHE_REUSE:-256}"
  LLM_SERVICE_DISABLE_WARMUP="${LLM_SERVICE_DISABLE_WARMUP:-true}"
  LLM_SERVICE_DISABLE_WEBUI="${LLM_SERVICE_DISABLE_WEBUI:-true}"
  LLM_SERVICE_EXTRA_ARGS="${LLM_SERVICE_EXTRA_ARGS:-}"
  VLLM_IMAGE="${VLLM_IMAGE:-vllm/vllm-openai-rocm:latest}"
  HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"

  GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
  GATEWAY_PORT="${GATEWAY_PORT:-8765}"
  NLP_SERVICE_HOST="${NLP_SERVICE_HOST:-127.0.0.1}"
  NLP_SERVICE_PORT="${NLP_SERVICE_PORT:-8767}"
  EXPORT_SERVICE_HOST="${EXPORT_SERVICE_HOST:-127.0.0.1}"
  EXPORT_SERVICE_PORT="${EXPORT_SERVICE_PORT:-8768}"
  LEXICON_SERVICE_HOST="${LEXICON_SERVICE_HOST:-127.0.0.1}"
  LEXICON_SERVICE_PORT="${LEXICON_SERVICE_PORT:-4011}"
  ASSIGNMENTS_SERVICE_HOST="${ASSIGNMENTS_SERVICE_HOST:-127.0.0.1}"
  ASSIGNMENTS_SERVICE_PORT="${ASSIGNMENTS_SERVICE_PORT:-4012}"
  OWNER_SERVICES_STORAGE_BACKEND="${OWNER_SERVICES_STORAGE_BACKEND:-}"
  OWNER_SERVICES_POSTGRES_URL="${OWNER_SERVICES_POSTGRES_URL:-postgresql://postgres:postgres@127.0.0.1:5432/vocabulary}"
  OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE="${OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE:-}"
  GATEWAY_PARSE_BACKEND="${GATEWAY_PARSE_BACKEND:-nlp}"
  GATEWAY_LEXICON_BACKEND="${GATEWAY_LEXICON_BACKEND:-service}"
  GATEWAY_ASSIGNMENTS_BACKEND="${GATEWAY_ASSIGNMENTS_BACKEND:-service}"
  GATEWAY_STATISTICS_BACKEND="${GATEWAY_STATISTICS_BACKEND:-composed}"
  GATEWAY_EXPORT_BACKEND="${GATEWAY_EXPORT_BACKEND:-service}"

  if [ "$POSTGRES_MODE" = "1" ]; then
    OWNER_SERVICES_STORAGE_BACKEND="${OWNER_SERVICES_STORAGE_BACKEND:-postgres}"
    OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE="${OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE:-1}"
  fi
  OWNER_SERVICES_STORAGE_BACKEND="${OWNER_SERVICES_STORAGE_BACKEND:-sqlite}"
  OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE="${OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE:-0}"
  if [ -z "$START_POSTGRES_VIA_COMPOSE" ]; then
    [ "$POSTGRES_MODE" = "1" ] && START_POSTGRES_VIA_COMPOSE=1 || START_POSTGRES_VIA_COMPOSE=0
  fi

  mapfile -t _dsn_parts < <(parse_postgres_dsn "$OWNER_SERVICES_POSTGRES_URL")
  POSTGRES_DSN_HOST="${_dsn_parts[0]:-}"
  POSTGRES_DSN_PORT="${_dsn_parts[1]:-5432}"

  LEXICON_STORAGE_BACKEND="${LEXICON_STORAGE_BACKEND:-$OWNER_SERVICES_STORAGE_BACKEND}"
  LEXICON_POSTGRES_URL="${LEXICON_POSTGRES_URL:-$OWNER_SERVICES_POSTGRES_URL}"
  LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE="${LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE:-$OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE}"
  LEXICON_POSTGRES_SCHEMA="${LEXICON_POSTGRES_SCHEMA:-lexicon}"
  ASSIGNMENTS_STORAGE_BACKEND="${ASSIGNMENTS_STORAGE_BACKEND:-$OWNER_SERVICES_STORAGE_BACKEND}"
  ASSIGNMENTS_POSTGRES_URL="${ASSIGNMENTS_POSTGRES_URL:-$OWNER_SERVICES_POSTGRES_URL}"
  ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE="${ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE:-$OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE}"
  ASSIGNMENTS_POSTGRES_SCHEMA="${ASSIGNMENTS_POSTGRES_SCHEMA:-assignments}"

  [ "$OWNER_SERVICES_STORAGE_BACKEND" = "postgres" ] && echo "[start] Owner services storage backend: postgres"

  ROCM_DOCKER_GPU_FLAGS="$(build_python_docker_gpu_flags)"
  if [ "${BERT_DEVICE:-cpu}" = "cuda" ]; then
    PYTHON_IMAGE="${PYTHON_IMAGE_GPU}"
    PYTHON_DOCKER_GPU_FLAGS="${ROCM_DOCKER_GPU_FLAGS}"
  else
    PYTHON_IMAGE="${PYTHON_IMAGE_CPU}"
  fi
  if [ -z "${PYTHON_BACKEND}" ]; then
    if command -v docker >/dev/null 2>&1 && docker image inspect "${PYTHON_IMAGE}" >/dev/null 2>&1; then
      PYTHON_BACKEND=docker
    else
      PYTHON_BACKEND=native
    fi
  fi
  echo "[start] Python backend: ${PYTHON_BACKEND} (image: ${PYTHON_IMAGE})"
}

print_runtime_config() {
  cat <<EOF
POSTGRES_MODE=$POSTGRES_MODE
LLM_SERVICE_ENABLED=$LLM_SERVICE_ENABLED
LLM_SERVICE_RUNTIME=$LLM_SERVICE_RUNTIME
LLM_SERVICE_MODEL=$LLM_SERVICE_MODEL
LLM_SERVICE_HOST=$LLM_SERVICE_HOST
LLM_SERVICE_PORT=$LLM_SERVICE_PORT
LLM_SERVICE_MAX_MODEL_LEN=$LLM_SERVICE_MAX_MODEL_LEN
LLM_SERVICE_GPU_UTIL=$LLM_SERVICE_GPU_UTIL
LLM_SERVICE_READY_TIMEOUT_SECONDS=$LLM_SERVICE_READY_TIMEOUT_SECONDS
THIRD_PASS_LLM_TIMEOUT_MS=$THIRD_PASS_LLM_TIMEOUT_MS
GATEWAY_JOB_TTL_MS=${GATEWAY_JOB_TTL_MS:-}
LLM_SERVICE_EXECUTABLE=$LLM_SERVICE_EXECUTABLE
LLM_SERVICE_MODEL_PATH=$LLM_SERVICE_MODEL_PATH
LLM_SERVICE_N_GPU_LAYERS=$LLM_SERVICE_N_GPU_LAYERS
LLM_SERVICE_THREADS=$LLM_SERVICE_THREADS
LLM_SERVICE_BATCH_SIZE=$LLM_SERVICE_BATCH_SIZE
LLM_SERVICE_UBATCH_SIZE=$LLM_SERVICE_UBATCH_SIZE
LLM_SERVICE_THREADS_BATCH=$LLM_SERVICE_THREADS_BATCH
LLM_SERVICE_THREADS_HTTP=$LLM_SERVICE_THREADS_HTTP
LLM_SERVICE_PARALLEL_SLOTS=$LLM_SERVICE_PARALLEL_SLOTS
LLM_SERVICE_FLASH_ATTN=$LLM_SERVICE_FLASH_ATTN
LLM_SERVICE_CACHE_REUSE=$LLM_SERVICE_CACHE_REUSE
LLM_SERVICE_DISABLE_WARMUP=$LLM_SERVICE_DISABLE_WARMUP
LLM_SERVICE_DISABLE_WEBUI=$LLM_SERVICE_DISABLE_WEBUI
LLM_SERVICE_EXTRA_ARGS=$LLM_SERVICE_EXTRA_ARGS
VLLM_IMAGE=$VLLM_IMAGE
HF_CACHE=$HF_CACHE
GATEWAY_PARSE_BACKEND=$GATEWAY_PARSE_BACKEND
GATEWAY_LEXICON_BACKEND=$GATEWAY_LEXICON_BACKEND
GATEWAY_ASSIGNMENTS_BACKEND=$GATEWAY_ASSIGNMENTS_BACKEND
GATEWAY_STATISTICS_BACKEND=$GATEWAY_STATISTICS_BACKEND
GATEWAY_EXPORT_BACKEND=$GATEWAY_EXPORT_BACKEND
OWNER_SERVICES_STORAGE_BACKEND=$OWNER_SERVICES_STORAGE_BACKEND
OWNER_SERVICES_POSTGRES_URL=$OWNER_SERVICES_POSTGRES_URL
OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE=$OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE
START_POSTGRES_VIA_COMPOSE=$START_POSTGRES_VIA_COMPOSE
POSTGRES_DSN_HOST=$POSTGRES_DSN_HOST
POSTGRES_DSN_PORT=$POSTGRES_DSN_PORT
LEXICON_STORAGE_BACKEND=$LEXICON_STORAGE_BACKEND
LEXICON_POSTGRES_URL=$LEXICON_POSTGRES_URL
LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE=$LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE
LEXICON_POSTGRES_SCHEMA=$LEXICON_POSTGRES_SCHEMA
ASSIGNMENTS_STORAGE_BACKEND=$ASSIGNMENTS_STORAGE_BACKEND
ASSIGNMENTS_POSTGRES_URL=$ASSIGNMENTS_POSTGRES_URL
ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE=$ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE
ASSIGNMENTS_POSTGRES_SCHEMA=$ASSIGNMENTS_POSTGRES_SCHEMA
FRONTEND_DEV_HOST=$FRONTEND_DEV_HOST
FRONTEND_DEV_PORT=$FRONTEND_DEV_PORT
STARTUP_TIMEOUT_SECONDS=$STARTUP_TIMEOUT_SECONDS
EOF
}

run_preflight_checks() {
  require_command python3 "Install Python 3 and ensure it is available in PATH."
  require_command npm "Install Node.js + npm and ensure it is available in PATH."

  if [ "${PYTHON_BACKEND}" = "docker" ]; then
    require_command docker "Install Docker Engine and ensure the daemon is running."
    if ! docker image inspect "${PYTHON_IMAGE}" >/dev/null 2>&1; then
      echo "[start] Python Docker image '${PYTHON_IMAGE}' not found."
      [ "${BERT_DEVICE:-cpu}" = "cuda" ] \
        && echo "[start] Соберите его: ./scripts/prepare_docker_runtime.sh --rocm" \
        || echo "[start] Соберите его: ./scripts/prepare_docker_runtime.sh"
      exit 1
    fi
  else
    assert_python_runtime_available
  fi

  if [ "$POSTGRES_MODE" = "1" ] && [ "$START_POSTGRES_VIA_COMPOSE" = "1" ] && \
     ! is_postgres_endpoint_reachable "$POSTGRES_DSN_HOST" "$POSTGRES_DSN_PORT"; then
    require_command docker "Install Docker Engine and ensure the daemon is running."
  fi

  if [ "$LLM_SERVICE_ENABLED" = "true" ]; then
    case "$LLM_SERVICE_RUNTIME" in
      vllm)
        require_command docker "Install Docker Engine and ensure the daemon is running."
        ;;
      llama_cpp)
        assert_llama_cpp_runtime_available
        ;;
      *)
        echo "[start] Unsupported LLM_SERVICE_RUNTIME: $LLM_SERVICE_RUNTIME"
        echo "[start] Supported values: llama_cpp, vllm"
        exit 1
        ;;
    esac
    require_port_free "$LLM_SERVICE_HOST" "$LLM_SERVICE_PORT" "llm-service"
  fi

  require_port_free "$NLP_SERVICE_HOST" "$NLP_SERVICE_PORT" "nlp-service"
  require_port_free "$EXPORT_SERVICE_HOST" "$EXPORT_SERVICE_PORT" "export-service"
  require_port_free "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" "lexicon-service"
  require_port_free "$ASSIGNMENTS_SERVICE_HOST" "$ASSIGNMENTS_SERVICE_PORT" "assignments-service"
  require_port_free "$GATEWAY_HOST" "$GATEWAY_PORT" "api-gateway"
  if $DEV_MODE; then
    require_port_free "$FRONTEND_DEV_HOST" "$FRONTEND_DEV_PORT" "frontend dev server"
  fi
}

ensure_node_dependencies() {
  if [ ! -d frontend/node_modules ]; then
    echo "[start] Installing frontend dependencies..."
    cd frontend && npm install
    cd "$SCRIPT_DIR"
  fi
  if [ ! -d backend/services/node_modules ]; then
    echo "[start] Installing service workspace dependencies..."
    cd backend/services && npm install
    cd "$SCRIPT_DIR"
  fi
}

bootstrap_runtime_assets() {
  ensure_local_postgres

  if $BUILD_FRONTEND || { ! $DEV_MODE && [ ! -d frontend/dist ]; }; then
    echo "[start] Building frontend..."
    cd frontend && npm run build
    cd "$SCRIPT_DIR"
    echo "[start] Frontend build complete."
  fi
}

start_runtime_services() {
  local local_llm_base_url="http://127.0.0.1:${LLM_SERVICE_PORT}"
  local enable_third_pass_llm_env="false"

  if $DEV_MODE; then
    start_managed_service "frontend dev server on http://${FRONTEND_DEV_HOST}:${FRONTEND_DEV_PORT}" \
      "$(build_frontend_dev_command)"
  fi

  if [ "$LLM_SERVICE_ENABLED" = "true" ]; then
    case "$LLM_SERVICE_RUNTIME" in
      vllm)
        if ! docker image inspect "${VLLM_IMAGE}" >/dev/null 2>&1; then
          echo "[start] vLLM image '${VLLM_IMAGE}' not found."
          echo "[start] Pull it once before startup: docker pull ${VLLM_IMAGE}"
          exit 1
        fi
        start_managed_service "LLM service (vLLM) on http://${LLM_SERVICE_HOST}:${LLM_SERVICE_PORT}" \
          "$(build_llm_vllm_command)"
        ;;
      llama_cpp)
        start_managed_service "LLM service (llama.cpp) on http://${LLM_SERVICE_HOST}:${LLM_SERVICE_PORT}" \
          "$(build_llm_llama_command)"
        ;;
    esac
    wait_for_llm_ready "LLM service" "$local_llm_base_url" "$LLM_SERVICE_READY_TIMEOUT_SECONDS"
    enable_third_pass_llm_env="true"
  fi

  start_managed_service "NLP capability service on http://${NLP_SERVICE_HOST}:${NLP_SERVICE_PORT}" \
    "$(build_nlp_command "$local_llm_base_url" "$enable_third_pass_llm_env")"
  start_managed_service "export capability service on http://${EXPORT_SERVICE_HOST}:${EXPORT_SERVICE_PORT}" \
    "$(build_export_command)"
  start_managed_service "lexicon service on http://${LEXICON_SERVICE_HOST}:${LEXICON_SERVICE_PORT}" \
    "$(build_lexicon_command)"
  start_managed_service "assignments service on http://${ASSIGNMENTS_SERVICE_HOST}:${ASSIGNMENTS_SERVICE_PORT}" \
    "$(build_assignments_command)"
  start_managed_service "gateway on http://${GATEWAY_HOST}:${GATEWAY_PORT}" \
    "$(build_gateway_command)"
}

wait_for_runtime_readiness() {
  wait_for_http_ready "NLP capability service" "http://${NLP_SERVICE_HOST}:${NLP_SERVICE_PORT}/internal/v1/system/health"
  wait_for_http_ready "export capability service" "http://${EXPORT_SERVICE_HOST}:${EXPORT_SERVICE_PORT}/internal/v1/system/health"
  wait_for_http_ready "lexicon service" "http://${LEXICON_SERVICE_HOST}:${LEXICON_SERVICE_PORT}/health"
  wait_for_http_ready "assignments service" "http://${ASSIGNMENTS_SERVICE_HOST}:${ASSIGNMENTS_SERVICE_PORT}/health"
  wait_for_http_ready "gateway health endpoint" "http://${GATEWAY_HOST}:${GATEWAY_PORT}/api/system/health"
  if $DEV_MODE; then
    wait_for_http_ready "frontend dev server" "http://${FRONTEND_DEV_HOST}:${FRONTEND_DEV_PORT}/"
  else
    wait_for_http_ready "gateway frontend" "http://${GATEWAY_HOST}:${GATEWAY_PORT}/"
  fi
}

announce_runtime_ready() {
  SERVICES_READY=true
  echo "[start] Stack is ready."
  echo "[start] Gateway: http://${GATEWAY_HOST}:${GATEWAY_PORT}"
  if $DEV_MODE; then
    echo "[start] Frontend dev server: http://${FRONTEND_DEV_HOST}:${FRONTEND_DEV_PORT}"
  fi
  echo "[start] Press Ctrl+C to stop all managed services."
}

wait_for_primary_service_exit() {
  local gateway_pid="${PIDS[${#PIDS[@]}-1]}"
  local wait_status
  set +e
  wait "$gateway_pid"
  wait_status=$?
  set -e
  echo "[start] $(service_name_by_pid "$gateway_pid") exited with code ${wait_status}; shutting down remaining services."
  exit "$wait_status"
}

start_main() {
  parse_start_args "$@"
  load_start_env_files
  apply_runtime_defaults

  if $PRINT_CONFIG; then
    print_runtime_config
    exit 0
  fi

  run_preflight_checks
  ensure_node_dependencies
  bootstrap_runtime_assets
  start_runtime_services
  wait_for_runtime_readiness
  announce_runtime_ready
  wait_for_primary_service_exit
}
