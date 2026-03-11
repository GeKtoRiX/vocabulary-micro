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
    COMPOSE_CMD=(docker compose)
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
    return 0
  fi
  return 1
}

resolve_path_if_relative() {
  local value="$1"
  if [ -z "$value" ]; then
    return 1
  fi
  if [[ "$value" = /* ]]; then
    printf '%s\n' "$value"
    return 0
  fi
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

resolve_executable_for_managed_llm() {
  local executable="$1"
  if [ -z "$executable" ]; then
    return 1
  fi
  if [[ "$executable" == */* ]]; then
    resolve_path_if_relative "$executable"
    return 0
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
    echo "[start] llama.cpp executable is not executable: $executable_path"
    exit 1
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

wait_for_postgres_container() {
  local container_id="$1" status="" attempt
  for attempt in $(seq 1 60); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then
      return 0
    fi
    sleep 1
  done
  echo "[start] Postgres container did not become healthy in time."
  "${COMPOSE_CMD[@]}" logs --tail 50 postgres || true
  return 1
}

ensure_local_postgres() {
  local container_id=""
  if [ "$POSTGRES_MODE" != "1" ]; then
    return 0
  fi
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
    echo "[start] Failed to resolve docker compose postgres container id."
    exit 1
  fi
  wait_for_postgres_container "$container_id"
  echo "[start] Local Postgres is healthy."
}

stop_local_postgres_if_started() {
  if [ "$POSTGRES_STARTED_BY_SCRIPT" != "1" ]; then
    return 0
  fi
  if [ "${#COMPOSE_CMD[@]}" -eq 0 ] && ! resolve_compose_command; then
    return 0
  fi
  echo "[start] Stopping local compose postgres ..."
  "${COMPOSE_CMD[@]}" stop postgres >/dev/null 2>&1 || true
}

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
      echo "${SERVICE_NAMES[$index]}"
      return 0
    fi
  done
  echo "managed service"
}

ensure_managed_processes_alive() {
  local index pid name status
  for index in "${!PIDS[@]}"; do
    pid="${PIDS[$index]}"
    name="${SERVICE_NAMES[$index]}"
    if kill -0 "$pid" 2>/dev/null; then
      continue
    fi
    set +e
    wait "$pid"
    status=$?
    set -e
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
  for pid in "${PIDS[@]:-}"; do
    wait "$pid" >/dev/null 2>&1 || true
  done
  set -e
}

cleanup() {
  local exit_code=$?
  if [ "$CLEANUP_RAN" = "1" ]; then
    return
  fi
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
