#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NET="python3 $SCRIPT_DIR/scripts/lib/net.py"

# Load nvm if available
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

BUILD_FRONTEND=false
DEV_MODE=false
RESTART_MODE=false
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

# Python backend: docker (рекомендуется) или native (устаревший).
PYTHON_BACKEND="${PYTHON_BACKEND:-}"
PYTHON_IMAGE_GPU="${PYTHON_IMAGE_GPU:-vocabulary-python-runtime-rocm:local}"
PYTHON_IMAGE_CPU="${PYTHON_IMAGE_CPU:-vocabulary-python-runtime:local}"
PYTHON_IMAGE=""
ROCM_DOCKER_GPU_FLAGS=""
PYTHON_DOCKER_GPU_FLAGS=""

# LLM service (все переменные читаются из env; defaults применяются после load_env)
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

# ── Env loading ───────────────────────────────────────────────────────────────

load_env_defaults_file() {
  local file_path="$1"
  local line key current_value
  if [ ! -f "$file_path" ]; then
    return 0
  fi
  echo "[start] Loading env defaults from ${file_path#$SCRIPT_DIR/} ..."
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"
    if [ -z "$line" ] || [ "${line:0:1}" = "#" ] || [[ "$line" != *=* ]]; then
      continue
    fi
    key="${line%%=*}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      continue
    fi
    current_value="${!key-}"
    if [ -n "${!key+x}" ] && [ -n "$current_value" ]; then
      continue
    fi
    eval "export ${line}"
  done < "$file_path"
}

# ── Network helpers ───────────────────────────────────────────────────────────

parse_postgres_dsn() {
  $NET parse-dsn "$1"
}

is_postgres_endpoint_reachable() {
  $NET tcp-probe "$1" "$2"
}

is_tcp_port_reachable() {
  $NET tcp-probe "$1" "$2"
}

is_local_postgres_host() {
  local host="$1"
  case "$host" in
    ""|127.0.0.1|localhost) return 0 ;;
    *) return 1 ;;
  esac
}

kill_port_owner() {
  local port="$1"
  # fuser -k посылает SIGTERM процессам, слушающим порт
  if fuser -k "${port}/tcp" >/dev/null 2>&1; then
    sleep 1
  fi
}

require_port_free() {
  local host="$1" port="$2" label="$3"
  if ! is_tcp_port_reachable "$host" "$port"; then
    return 0
  fi
  if $RESTART_MODE; then
    echo "[start] Порт ${host}:${port} занят (${label}); убиваю процесс ..."
    kill_port_owner "$port"
    if is_tcp_port_reachable "$host" "$port"; then
      echo "[start] Порт ${port} всё ещё занят после SIGTERM; принудительное завершение ..."
      fuser -k -9 "${port}/tcp" >/dev/null 2>&1 || true
      sleep 1
    fi
    return 0
  fi
  echo "[start] Port ${host}:${port} is already in use; cannot start ${label}."
  echo "[start] Use --restart to automatically stop existing processes."
  exit 1
}

wait_for_http_ready() {
  local name="$1" url="$2"
  local timeout_seconds="${3:-$STARTUP_TIMEOUT_SECONDS}"
  local expected_status="${4:-200}"
  local deadline=$((SECONDS + timeout_seconds))
  local attempt_output=""

  while [ "$SECONDS" -lt "$deadline" ]; do
    ensure_managed_processes_alive
    set +e
    attempt_output="$($NET http-probe "$url" "$expected_status" 2>&1)"
    local status=$?
    set -e
    if [ "$status" -eq 0 ]; then
      echo "[start] ${name} is ready at ${url}"
      return 0
    fi
    sleep 1
  done
  echo "[start] ${name} did not become ready at ${url} within ${timeout_seconds}s."
  [ -n "$attempt_output" ] && echo "[start] Last readiness probe: ${attempt_output}"
  return 1
}

wait_for_llm_ready() {
  local name="$1" base_url="$2"
  local timeout_seconds="${3:-$STARTUP_TIMEOUT_SECONDS}"
  local deadline=$((SECONDS + timeout_seconds))
  local attempt_output=""

  while [ "$SECONDS" -lt "$deadline" ]; do
    ensure_managed_processes_alive
    set +e
    attempt_output="$($NET llm-probe "$base_url" 2>&1)"
    local status=$?
    set -e
    if [ "$status" -eq 0 ]; then
      echo "[start] ${name} is ready at ${attempt_output}"
      return 0
    fi
    sleep 1
  done
  echo "[start] ${name} did not become ready within ${timeout_seconds}s."
  [ -n "$attempt_output" ] && echo "[start] Last readiness probe: ${attempt_output}"
  return 1
}

# ── System helpers ────────────────────────────────────────────────────────────

require_command() {
  local command_name="$1" help_text="$2"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "[start] Required command '$command_name' is not available."
    echo "[start] $help_text"
    exit 1
  fi
}

resolve_compose_command() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose); return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose); return 0
  fi
  return 1
}

resolve_path_if_relative() {
  local value="$1"
  if [ -z "$value" ]; then return 1; fi
  if [[ "$value" = /* ]]; then printf '%s\n' "$value"; return 0; fi
  printf '%s\n' "$SCRIPT_DIR/$value"
}

resolve_group_gid() {
  local group_line=""
  group_line="$(getent group "$1" 2>/dev/null || true)"
  [ -n "$group_line" ] && printf '%s\n' "$group_line" | cut -d: -f3
}

build_python_docker_gpu_flags() {
  local gpu_flags=(--device /dev/kfd --device /dev/dri)
  local gid=""
  gid="$(resolve_group_gid video || true)"
  [ -n "$gid" ] && gpu_flags+=(--group-add "$gid")
  gid="$(resolve_group_gid render || true)"
  [ -n "$gid" ] && gpu_flags+=(--group-add "$gid")
  printf '%q ' "${gpu_flags[@]}"
}

assert_python_runtime_available() {
  if ! python3 -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
    echo "[start] Python runtime dependencies are missing."
    echo "[start] Install them once with: pip install -r requirements.txt"
    exit 1
  fi
}

# ── LLM helpers ───────────────────────────────────────────────────────────────

resolve_executable_for_managed_llm() {
  local executable="$1"
  if [ -z "$executable" ]; then return 1; fi
  if [[ "$executable" == */* ]]; then
    resolve_path_if_relative "$executable"; return 0
  fi
  command -v "$executable" 2>/dev/null
}

assert_llama_cpp_runtime_available() {
  local executable_path model_path
  executable_path="$(resolve_executable_for_managed_llm "$LLM_SERVICE_EXECUTABLE" || true)"
  if [ -z "$executable_path" ]; then
    echo "[start] llama.cpp executable '${LLM_SERVICE_EXECUTABLE}' not found."
    echo "[start] Install llama.cpp and ensure 'llama-server' is in PATH,"
    echo "[start] or set LLM_SERVICE_EXECUTABLE to the local binary path."
    exit 1
  fi
  if [ ! -x "$executable_path" ]; then
    echo "[start] llama.cpp executable is not executable: $executable_path"; exit 1
  fi
  model_path="$(resolve_path_if_relative "$LLM_SERVICE_MODEL_PATH" || true)"
  if [ -z "$model_path" ]; then
    echo "[start] LLM_SERVICE_MODEL_PATH must point to a local .gguf file when LLM_SERVICE_RUNTIME=llama_cpp."
    exit 1
  fi
  if [ ! -f "$model_path" ]; then
    echo "[start] llama.cpp model not found: $model_path"
    echo "[start] Download a GGUF file and set LLM_SERVICE_MODEL_PATH accordingly."
    exit 1
  fi
}

# ── Postgres helpers ───────────────────────────────────────────────────────────

wait_for_postgres_container() {
  local container_id="$1" status="" attempt
  for attempt in $(seq 1 60); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then return 0; fi
    sleep 1
  done
  echo "[start] Postgres container did not become healthy in time."
  "${COMPOSE_CMD[@]}" logs --tail 50 postgres || true
  return 1
}

ensure_local_postgres() {
  local container_id=""
  if [ "$POSTGRES_MODE" != "1" ]; then return 0; fi
  if [ "$START_POSTGRES_VIA_COMPOSE" != "1" ]; then
    echo "[start] Local Postgres autostart disabled; expecting external Postgres at ${OWNER_SERVICES_POSTGRES_URL}."
    return 0
  fi
  if ! is_local_postgres_host "$POSTGRES_DSN_HOST"; then
    echo "[start] Skipping compose Postgres autostart because DSN host is '${POSTGRES_DSN_HOST}'."
    return 0
  fi
  if is_postgres_endpoint_reachable "$POSTGRES_DSN_HOST" "$POSTGRES_DSN_PORT"; then
    echo "[start] Postgres is already reachable at ${POSTGRES_DSN_HOST}:${POSTGRES_DSN_PORT}; skipping compose autostart."
    return 0
  fi
  if ! resolve_compose_command; then
    echo "[start] Docker Compose is required for automatic local Postgres bootstrap."
    echo "[start] Install Docker Compose or set START_POSTGRES_VIA_COMPOSE=0 to use an external Postgres."
    exit 1
  fi
  export POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-$POSTGRES_DSN_PORT}"
  if ! docker image inspect postgres:16 >/dev/null 2>&1; then
    echo "[start] Local postgres image is missing."
    echo "[start] Run ./scripts/prepare_docker_runtime.sh once before startup so runtime does not download images on boot."
    exit 1
  fi
  echo "[start] Ensuring local Postgres is running via docker compose on 127.0.0.1:${POSTGRES_HOST_PORT} ..."
  if ! "${COMPOSE_CMD[@]}" up -d postgres; then
    echo "[start] Failed to bootstrap docker compose postgres."
    echo "[start] Check Docker daemon access, ensure images are preloaded via ./scripts/prepare_docker_runtime.sh,"
    echo "[start] or set START_POSTGRES_VIA_COMPOSE=0 to use an external Postgres."
    exit 1
  fi
  POSTGRES_STARTED_BY_SCRIPT=1
  container_id="$("${COMPOSE_CMD[@]}" ps -q postgres)"
  if [ -z "$container_id" ]; then
    echo "[start] Failed to resolve docker compose postgres container id."; exit 1
  fi
  wait_for_postgres_container "$container_id"
  echo "[start] Local Postgres is healthy."
}

stop_local_postgres_if_started() {
  if [ "$POSTGRES_STARTED_BY_SCRIPT" != "1" ]; then return 0; fi
  if [ "${#COMPOSE_CMD[@]}" -eq 0 ] && ! resolve_compose_command; then return 0; fi
  echo "[start] Stopping local compose postgres ..."
  "${COMPOSE_CMD[@]}" stop postgres >/dev/null 2>&1 || true
}

# ── Process management ────────────────────────────────────────────────────────

start_managed_service() {
  local name="$1" command="$2" pid
  echo "[start] Starting ${name} ..."
  if command -v setsid >/dev/null 2>&1; then
    setsid bash -lc "$command" &
  else
    bash -lc "$command" &
  fi
  pid="$!"
  PIDS+=("$pid")
  PROCESS_GROUPS+=("$pid")
  SERVICE_NAMES+=("$name")
  echo "[start] ${name} PID: ${pid}"
}

service_name_by_pid() {
  local pid="$1" index
  for index in "${!PIDS[@]}"; do
    if [ "${PIDS[$index]}" = "$pid" ]; then
      echo "${SERVICE_NAMES[$index]}"; return 0
    fi
  done
  echo "managed service"
}

ensure_managed_processes_alive() {
  local index pid name status
  for index in "${!PIDS[@]}"; do
    pid="${PIDS[$index]}"
    name="${SERVICE_NAMES[$index]}"
    if kill -0 "$pid" 2>/dev/null; then continue; fi
    set +e; wait "$pid"; status=$?; set -e
    echo "[start] ${name} exited unexpectedly with code ${status}."
    return 1
  done
  return 0
}

cleanup_managed_processes() {
  local pgid deadline all_stopped
  for pgid in "${PROCESS_GROUPS[@]:-}"; do
    kill -0 "$pgid" 2>/dev/null && kill -TERM -- "-$pgid" 2>/dev/null || true
  done
  deadline=$((SECONDS + 15))
  while [ "$SECONDS" -lt "$deadline" ]; do
    all_stopped=true
    for pgid in "${PROCESS_GROUPS[@]:-}"; do
      kill -0 "$pgid" 2>/dev/null && all_stopped=false && break
    done
    $all_stopped && break
    sleep 1
  done
  for pgid in "${PROCESS_GROUPS[@]:-}"; do
    kill -0 "$pgid" 2>/dev/null && kill -KILL -- "-$pgid" 2>/dev/null || true
  done
  set +e
  for pid in "${PIDS[@]:-}"; do wait "$pid" >/dev/null 2>&1 || true; done
  set -e
}

cleanup() {
  local exit_code=$?
  if [ "$CLEANUP_RAN" = "1" ]; then return; fi
  CLEANUP_RAN=1
  set +e
  cleanup_managed_processes
  stop_local_postgres_if_started
  set -e
  exit "$exit_code"
}

handle_interrupt() {
  echo
  echo "[start] Interrupt received; shutting down services ..."
  exit 130
}

trap handle_interrupt INT TERM
trap cleanup EXIT

# ── Service command builders ───────────────────────────────────────────────────

build_nlp_command() {
  local cmd=""
  local llm_base_url="$1" enable_llm="$2"
  if [ "${PYTHON_BACKEND}" = "docker" ]; then
    printf -v cmd \
      'exec docker run --rm --network host -v %q:/app -e LEXICON_SERVICE_HOST=%q -e LEXICON_SERVICE_PORT=%q -e NLP_SERVICE_HOST=%q -e NLP_SERVICE_PORT=%q -e BERT_DEVICE=%q -e BERT_MODEL_NAME=%q -e BERT_LOCAL_FILES_ONLY=true -e BERT_TIMEOUT_MS=%q -e ENABLE_THIRD_PASS_LLM=%q -e THIRD_PASS_LLM_BASE_URL=%q -e THIRD_PASS_LLM_MODEL=%q -e THIRD_PASS_LLM_TIMEOUT_MS=%q -e LLAMA_SERVER_AUTOSTART_ENABLED=false -e HSA_OVERRIDE_GFX_VERSION=%q -e TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=%q -e TOKENIZERS_PARALLELISM=false %s %q python3 -m backend.python_services.nlp_service.main' \
      "$SCRIPT_DIR" "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
      "$NLP_SERVICE_HOST" "$NLP_SERVICE_PORT" \
      "${BERT_DEVICE:-cpu}" "${BERT_MODEL_NAME:-string_similarity}" "${BERT_TIMEOUT_MS:-12000}" \
      "$enable_llm" "$llm_base_url" "$LLM_SERVICE_MODEL" "$THIRD_PASS_LLM_TIMEOUT_MS" \
      "${HSA_OVERRIDE_GFX_VERSION:-}" "${TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL:-0}" \
      "${PYTHON_DOCKER_GPU_FLAGS}" "$PYTHON_IMAGE"
  else
    printf -v cmd \
      'cd %q && exec env LEXICON_SERVICE_HOST=%q LEXICON_SERVICE_PORT=%q NLP_SERVICE_HOST=%q NLP_SERVICE_PORT=%q BERT_DEVICE=%q BERT_MODEL_NAME=%q BERT_LOCAL_FILES_ONLY=%q BERT_TIMEOUT_MS=%q ENABLE_THIRD_PASS_LLM=%q THIRD_PASS_LLM_BASE_URL=%q THIRD_PASS_LLM_MODEL=%q THIRD_PASS_LLM_TIMEOUT_MS=%q LLAMA_SERVER_AUTOSTART_ENABLED=false HSA_OVERRIDE_GFX_VERSION=%q TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=%q TOKENIZERS_PARALLELISM=false python3 -m backend.python_services.nlp_service.main' \
      "$SCRIPT_DIR" "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
      "$NLP_SERVICE_HOST" "$NLP_SERVICE_PORT" \
      "${BERT_DEVICE:-cpu}" "${BERT_MODEL_NAME:-string_similarity}" "${BERT_LOCAL_FILES_ONLY:-true}" \
      "${BERT_TIMEOUT_MS:-12000}" "$enable_llm" "$llm_base_url" "$LLM_SERVICE_MODEL" \
      "$THIRD_PASS_LLM_TIMEOUT_MS" "${HSA_OVERRIDE_GFX_VERSION:-}" "${TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL:-0}"
  fi
  printf '%s' "$cmd"
}

build_export_command() {
  local cmd=""
  if [ "${PYTHON_BACKEND}" = "docker" ]; then
    printf -v cmd \
      'exec docker run --rm --network host -v %q:/app -e LEXICON_SERVICE_HOST=%q -e LEXICON_SERVICE_PORT=%q -e EXPORT_SERVICE_HOST=%q -e EXPORT_SERVICE_PORT=%q -e TOKENIZERS_PARALLELISM=false %q python3 -m backend.python_services.export_service.main' \
      "$SCRIPT_DIR" "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
      "$EXPORT_SERVICE_HOST" "$EXPORT_SERVICE_PORT" "$PYTHON_IMAGE"
  else
    printf -v cmd \
      'cd %q && exec env LEXICON_SERVICE_HOST=%q LEXICON_SERVICE_PORT=%q EXPORT_SERVICE_HOST=%q EXPORT_SERVICE_PORT=%q python3 -m backend.python_services.export_service.main' \
      "$SCRIPT_DIR" "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
      "$EXPORT_SERVICE_HOST" "$EXPORT_SERVICE_PORT"
  fi
  printf '%s' "$cmd"
}

build_lexicon_command() {
  local cmd=""
  printf -v cmd \
    'cd %q && exec env LEXICON_SERVICE_HOST=%q LEXICON_SERVICE_PORT=%q OWNER_SERVICES_STORAGE_BACKEND=%q OWNER_SERVICES_POSTGRES_URL=%q OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE=%q LEXICON_STORAGE_BACKEND=%q LEXICON_POSTGRES_URL=%q LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE=%q LEXICON_POSTGRES_SCHEMA=%q npm --workspace @vocabulary/lexicon-service run dev' \
    "$SCRIPT_DIR/backend/services" \
    "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
    "$OWNER_SERVICES_STORAGE_BACKEND" "$OWNER_SERVICES_POSTGRES_URL" "$OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE" \
    "$LEXICON_STORAGE_BACKEND" "$LEXICON_POSTGRES_URL" "$LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE" "$LEXICON_POSTGRES_SCHEMA"
  printf '%s' "$cmd"
}

build_assignments_command() {
  local cmd=""
  printf -v cmd \
    'cd %q && exec env ASSIGNMENTS_SERVICE_HOST=%q ASSIGNMENTS_SERVICE_PORT=%q OWNER_SERVICES_STORAGE_BACKEND=%q OWNER_SERVICES_POSTGRES_URL=%q OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE=%q ASSIGNMENTS_STORAGE_BACKEND=%q ASSIGNMENTS_POSTGRES_URL=%q ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE=%q ASSIGNMENTS_POSTGRES_SCHEMA=%q npm --workspace @vocabulary/assignments-service run dev' \
    "$SCRIPT_DIR/backend/services" \
    "$ASSIGNMENTS_SERVICE_HOST" "$ASSIGNMENTS_SERVICE_PORT" \
    "$OWNER_SERVICES_STORAGE_BACKEND" "$OWNER_SERVICES_POSTGRES_URL" "$OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE" \
    "$ASSIGNMENTS_STORAGE_BACKEND" "$ASSIGNMENTS_POSTGRES_URL" "$ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE" "$ASSIGNMENTS_POSTGRES_SCHEMA"
  printf '%s' "$cmd"
}

build_gateway_command() {
  local cmd=""
  printf -v cmd \
    'cd %q && exec env GATEWAY_HOST=%q GATEWAY_PORT=%q NLP_SERVICE_HOST=%q NLP_SERVICE_PORT=%q EXPORT_SERVICE_HOST=%q EXPORT_SERVICE_PORT=%q LEXICON_SERVICE_HOST=%q LEXICON_SERVICE_PORT=%q ASSIGNMENTS_SERVICE_HOST=%q ASSIGNMENTS_SERVICE_PORT=%q GATEWAY_PARSE_BACKEND=%q GATEWAY_LEXICON_BACKEND=%q GATEWAY_ASSIGNMENTS_BACKEND=%q GATEWAY_STATISTICS_BACKEND=%q GATEWAY_EXPORT_BACKEND=%q GATEWAY_SERVE_STATIC=%q npm --workspace @vocabulary/api-gateway run dev' \
    "$SCRIPT_DIR/backend/services" \
    "$GATEWAY_HOST" "$GATEWAY_PORT" \
    "$NLP_SERVICE_HOST" "$NLP_SERVICE_PORT" \
    "$EXPORT_SERVICE_HOST" "$EXPORT_SERVICE_PORT" \
    "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
    "$ASSIGNMENTS_SERVICE_HOST" "$ASSIGNMENTS_SERVICE_PORT" \
    "$GATEWAY_PARSE_BACKEND" "$GATEWAY_LEXICON_BACKEND" "$GATEWAY_ASSIGNMENTS_BACKEND" \
    "$GATEWAY_STATISTICS_BACKEND" "$GATEWAY_EXPORT_BACKEND" \
    "$([ "$DEV_MODE" = true ] && echo 0 || echo "${GATEWAY_SERVE_STATIC:-1}")"
  printf '%s' "$cmd"
}

build_llm_vllm_command() {
  local cmd=""
  printf -v cmd \
    'exec docker run --rm --network host -v %q:/root/.cache/huggingface -e HSA_OVERRIDE_GFX_VERSION=%q %s %q %q --host %q --port %q --quantization fp8 --max-model-len %q --gpu-memory-utilization %q --reasoning-parser qwen3' \
    "$HF_CACHE" "${HSA_OVERRIDE_GFX_VERSION:-11.0.0}" "${ROCM_DOCKER_GPU_FLAGS}" \
    "$VLLM_IMAGE" "$LLM_SERVICE_MODEL" \
    "$LLM_SERVICE_HOST" "$LLM_SERVICE_PORT" "$LLM_SERVICE_MAX_MODEL_LEN" "$LLM_SERVICE_GPU_UTIL"
  printf '%s' "$cmd"
}

build_llm_llama_command() {
  local executable_path model_path cmd=""
  executable_path="$(resolve_executable_for_managed_llm "$LLM_SERVICE_EXECUTABLE")"
  model_path="$(resolve_path_if_relative "$LLM_SERVICE_MODEL_PATH")"
  printf -v cmd \
    'exec %q --host %q --port %q --model %q --alias %q --ctx-size %q --n-gpu-layers %q --batch-size %q --ubatch-size %q --parallel %q --flash-attn %q' \
    "$executable_path" "$LLM_SERVICE_HOST" "$LLM_SERVICE_PORT" \
    "$model_path" "$LLM_SERVICE_MODEL" "$LLM_SERVICE_MAX_MODEL_LEN" "$LLM_SERVICE_N_GPU_LAYERS" \
    "$LLM_SERVICE_BATCH_SIZE" "$LLM_SERVICE_UBATCH_SIZE" "$LLM_SERVICE_PARALLEL_SLOTS" "$LLM_SERVICE_FLASH_ATTN"
  [ "${LLM_SERVICE_THREADS}" -gt 0 ]      && printf -v cmd '%s --threads %q'       "$cmd" "$LLM_SERVICE_THREADS"
  [ "${LLM_SERVICE_THREADS_BATCH}" -gt 0 ] && printf -v cmd '%s --threads-batch %q' "$cmd" "$LLM_SERVICE_THREADS_BATCH"
  [ "${LLM_SERVICE_THREADS_HTTP}" -gt 0 ]  && printf -v cmd '%s --threads-http %q'  "$cmd" "$LLM_SERVICE_THREADS_HTTP"
  [ "${LLM_SERVICE_CACHE_REUSE}" -gt 0 ]   && printf -v cmd '%s --cache-reuse %q'   "$cmd" "$LLM_SERVICE_CACHE_REUSE"
  [ "$LLM_SERVICE_DISABLE_WARMUP" = "true" ] && cmd="${cmd} --no-warmup"
  [ "$LLM_SERVICE_DISABLE_WEBUI" = "true" ]  && cmd="${cmd} --no-webui"
  [ -n "$LLM_SERVICE_EXTRA_ARGS" ]           && cmd="${cmd} ${LLM_SERVICE_EXTRA_ARGS}"
  printf '%s' "$cmd"
}

# ── Argument parsing ──────────────────────────────────────────────────────────

for arg in "$@"; do
  case "$arg" in
    --build)        BUILD_FRONTEND=true ;;
    --dev)          DEV_MODE=true ;;
    --restart)      RESTART_MODE=true ;;
    --postgres)     POSTGRES_MODE=1 ;;
    --print-config) PRINT_CONFIG=true ;;
    --help)
      cat <<EOF
Usage: $0 [--build] [--dev] [--restart] [--postgres] [--print-config]
  --build         Build frontend before starting server
  --dev           Start Vite dev server instead of serving built files
  --restart       Kill any existing processes on managed ports before starting
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
      exit 0
      ;;
  esac
done

# ── Load env files ─────────────────────────────────────────────────────────────

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

# ── Apply defaults ─────────────────────────────────────────────────────────────

LLM_SERVICE_ENABLED="${LLM_SERVICE_ENABLED:-false}"
LLM_SERVICE_RUNTIME="${LLM_SERVICE_RUNTIME:-llama_cpp}"
LLM_SERVICE_MODEL="${LLM_SERVICE_MODEL:-Qwen3.5-9B-GGUF}"
LLM_SERVICE_HOST="${LLM_SERVICE_HOST:-127.0.0.1}"
LLM_SERVICE_PORT="${LLM_SERVICE_PORT:-8000}"
LLM_SERVICE_MAX_MODEL_LEN="${LLM_SERVICE_MAX_MODEL_LEN:-8192}"
LLM_SERVICE_GPU_UTIL="${LLM_SERVICE_GPU_UTIL:-0.90}"
LLM_SERVICE_READY_TIMEOUT_SECONDS="${LLM_SERVICE_READY_TIMEOUT_SECONDS:-900}"
if [ -z "${THIRD_PASS_LLM_TIMEOUT_MS:-}" ]; then
  [ "${LLM_SERVICE_RUNTIME}" = "llama_cpp" ] && THIRD_PASS_LLM_TIMEOUT_MS="240000" || THIRD_PASS_LLM_TIMEOUT_MS="120000"
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

# ── Print config and exit ─────────────────────────────────────────────────────

if $PRINT_CONFIG; then
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
  exit 0
fi

# ── Pre-flight checks ─────────────────────────────────────────────────────────

require_command python3 "Install Python 3 and ensure it is available in PATH."
require_command npm    "Install Node.js + npm and ensure they are available in PATH."

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
    vllm)      require_command docker "Install Docker Engine and ensure the daemon is running." ;;
    llama_cpp) assert_llama_cpp_runtime_available ;;
    *)
      echo "[start] Unsupported LLM_SERVICE_RUNTIME: $LLM_SERVICE_RUNTIME"
      echo "[start] Supported values: llama_cpp, vllm"
      exit 1 ;;
  esac
  require_port_free "$LLM_SERVICE_HOST" "$LLM_SERVICE_PORT" "llm-service"
fi

require_port_free "$NLP_SERVICE_HOST"         "$NLP_SERVICE_PORT"         "nlp-service"
require_port_free "$EXPORT_SERVICE_HOST"      "$EXPORT_SERVICE_PORT"      "export-service"
require_port_free "$LEXICON_SERVICE_HOST"     "$LEXICON_SERVICE_PORT"     "lexicon-service"
require_port_free "$ASSIGNMENTS_SERVICE_HOST" "$ASSIGNMENTS_SERVICE_PORT" "assignments-service"
require_port_free "$GATEWAY_HOST"             "$GATEWAY_PORT"             "api-gateway"
$DEV_MODE && require_port_free "$FRONTEND_DEV_HOST" "$FRONTEND_DEV_PORT" "frontend dev server"

# ── Install dependencies ──────────────────────────────────────────────────────

if [ ! -d frontend/node_modules ]; then
  echo "[start] Installing frontend dependencies..."
  cd frontend && npm install; cd "$SCRIPT_DIR"
fi
if [ ! -d backend/services/node_modules ]; then
  echo "[start] Installing service workspace dependencies..."
  cd backend/services && npm install; cd "$SCRIPT_DIR"
fi

# ── Bootstrap ─────────────────────────────────────────────────────────────────

ensure_local_postgres

if $BUILD_FRONTEND || { ! $DEV_MODE && [ ! -d frontend/dist ]; }; then
  echo "[start] Building frontend..."
  cd frontend && npm run build; cd "$SCRIPT_DIR"
  echo "[start] Frontend build complete."
fi

# ── Start services ────────────────────────────────────────────────────────────

if $DEV_MODE; then
  local_frontend_command=""
  printf -v local_frontend_command 'cd %q && exec npm run dev -- --host %q --port %q --strictPort' \
    "$SCRIPT_DIR/frontend" "$FRONTEND_DEV_HOST" "$FRONTEND_DEV_PORT"
  start_managed_service "frontend dev server on http://${FRONTEND_DEV_HOST}:${FRONTEND_DEV_PORT}" "$local_frontend_command"
fi

local_llm_base_url="http://127.0.0.1:${LLM_SERVICE_PORT}"
enable_third_pass_llm_env="false"
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
  wait_for_llm_ready "LLM service" "${local_llm_base_url}" "${LLM_SERVICE_READY_TIMEOUT_SECONDS}"
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

# ── Wait for readiness ────────────────────────────────────────────────────────

wait_for_http_ready "NLP capability service"   "http://${NLP_SERVICE_HOST}:${NLP_SERVICE_PORT}/internal/v1/system/health"
wait_for_http_ready "export capability service" "http://${EXPORT_SERVICE_HOST}:${EXPORT_SERVICE_PORT}/internal/v1/system/health"
wait_for_http_ready "lexicon service"           "http://${LEXICON_SERVICE_HOST}:${LEXICON_SERVICE_PORT}/health"
wait_for_http_ready "assignments service"       "http://${ASSIGNMENTS_SERVICE_HOST}:${ASSIGNMENTS_SERVICE_PORT}/health"
wait_for_http_ready "gateway health endpoint"   "http://${GATEWAY_HOST}:${GATEWAY_PORT}/api/system/health"
if $DEV_MODE; then
  wait_for_http_ready "frontend dev server" "http://${FRONTEND_DEV_HOST}:${FRONTEND_DEV_PORT}/"
else
  wait_for_http_ready "gateway frontend" "http://${GATEWAY_HOST}:${GATEWAY_PORT}/"
fi

# ── Running ───────────────────────────────────────────────────────────────────

SERVICES_READY=true
echo "[start] Stack is ready."
echo "[start] Gateway: http://${GATEWAY_HOST}:${GATEWAY_PORT}"
$DEV_MODE && echo "[start] Frontend dev server: http://${FRONTEND_DEV_HOST}:${FRONTEND_DEV_PORT}"
echo "[start] Press Ctrl+C to stop all managed services."

GATEWAY_PID="${PIDS[${#PIDS[@]}-1]}"
set +e; wait "$GATEWAY_PID"; wait_status=$?; set -e
echo "[start] $(service_name_by_pid "$GATEWAY_PID") exited with code ${wait_status}; shutting down remaining services."
exit "$wait_status"
