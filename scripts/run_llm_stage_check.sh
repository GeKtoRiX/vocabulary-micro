#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

LLM_SERVICE_RUNTIME="${LLM_SERVICE_RUNTIME:-llama_cpp}"
VLLM_IMAGE="${VLLM_IMAGE:-vllm/vllm-openai-rocm:latest}"
LLAMA_CPP_DOCKER_IMAGE="${LLAMA_CPP_DOCKER_IMAGE:-ghcr.io/ggml-org/llama.cpp:server}"
LLAMA_CPP_MODEL_REPO="${LLAMA_CPP_MODEL_REPO:-lmstudio-community/Qwen3.5-9B-GGUF}"
LLAMA_CPP_MODEL_FILE="${LLAMA_CPP_MODEL_FILE:-Qwen3.5-9B-Q4_K_M.gguf}"
LLAMA_CPP_MODEL_DIR="${LLAMA_CPP_MODEL_DIR:-$ROOT_DIR/backend/python_services/infrastructure/runtime/models/lmstudio-community-Qwen3.5-9B-GGUF}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8765}"
TEXT="${LLM_STAGE_CHECK_TEXT:-This project should take into account phrases such as carry out, look into, and break down when parsing text.}"
LOG_DIR="${LLM_STAGE_CHECK_LOG_DIR:-$ROOT_DIR/backend/python_services/infrastructure/runtime/logs}"
START_LOG="${LLM_STAGE_CHECK_LOG:-$LOG_DIR/llm_stage_check_start.log}"
SSE_LOG="${LLM_STAGE_CHECK_SSE_LOG:-$LOG_DIR/llm_stage_check_sse.log}"
DIAG_LOG="${LLM_STAGE_CHECK_DIAG_LOG:-$LOG_DIR/llm_stage_check_diag.log}"
START_TIMEOUT_SECONDS="${LLM_STAGE_CHECK_START_TIMEOUT_SECONDS:-900}"
HEARTBEAT_SECONDS="${LLM_STAGE_CHECK_HEARTBEAT_SECONDS:-20}"
START_PID=""
KEEP_RUNNING=0
STOP_EXISTING=0

print_help() {
  cat <<EOF
Использование:
  bash scripts/run_llm_stage_check.sh

Что делает:
  1. Проверяет локальные зависимости для выбранного LLM runtime.
  2. Для runtime=vllm подтягивает образ ${VLLM_IMAGE}.
  2a. Для runtime=llama_cpp при необходимости докачивает GGUF и подтягивает образ ${LLAMA_CPP_DOCKER_IMAGE}.
  3. Поднимает стек через bash start.sh с LLM_SERVICE_ENABLED=true.
  4. Периодически печатает heartbeat по этапам ожидания.
  5. Ждёт готовности gateway.
  6. Запускает POST /api/parse с third_pass_enabled=true.
  7. Сохраняет и печатает SSE stream, затем проверяет наличие stage_progress для nlp и llm.
  8. При ошибке автоматически сохраняет диагностический dump.

Переменные окружения:
  LLM_SERVICE_RUNTIME                 llama_cpp или vllm.
  VLLM_IMAGE                         Docker image для vLLM.
  LLAMA_CPP_DOCKER_IMAGE             Docker image для llama.cpp server.
  LLAMA_CPP_MODEL_REPO               Hugging Face repo с GGUF моделью.
  LLAMA_CPP_MODEL_FILE               Имя GGUF файла.
  LLAMA_CPP_MODEL_DIR                Локальная директория для GGUF файла.
  GATEWAY_URL                        Базовый URL gateway (default: http://127.0.0.1:8765).
  LLM_STAGE_CHECK_TEXT               Текст для parse-проверки.
  LLM_STAGE_CHECK_LOG_DIR            Директория для логов.
  LLM_STAGE_CHECK_LOG                Файл лога для start.sh.
  LLM_STAGE_CHECK_SSE_LOG            Файл сырого SSE stream.
  LLM_STAGE_CHECK_DIAG_LOG           Файл диагностического dump.
  LLM_STAGE_CHECK_REQUIRE_THIRD_PASS_OCCURRENCES
                                     Требовать непустой third-pass summary.
  LLM_STAGE_CHECK_EXPECT_TYPES       CSV-список ожидаемых expression_type.
  LLM_STAGE_CHECK_EXPECT_FORMS       CSV-список ожидаемых canonical_form/surface.
  LLM_STAGE_CHECK_START_TIMEOUT_SECONDS
                                     Сколько ждать готовности стека.
  LLM_STAGE_CHECK_HEARTBEAT_SECONDS  Интервал heartbeat-логов при ожидании.

Примеры:
  bash scripts/run_llm_stage_check.sh
  bash scripts/run_llm_stage_check.sh --keep-running
  bash scripts/run_llm_stage_check.sh --stop-existing
  LLM_STAGE_CHECK_TEXT="Carry out the task and look into the issue." bash scripts/run_llm_stage_check.sh
  LLM_STAGE_CHECK_REQUIRE_THIRD_PASS_OCCURRENCES=true \
  LLM_STAGE_CHECK_EXPECT_TYPES=phrasal_verb,idiom \
  bash scripts/run_llm_stage_check.sh
EOF
}

if (($# > 0)); then
  for arg in "$@"; do
    case "$arg" in
      --help|-h)
        print_help
        exit 0
        ;;
      --keep-running)
        KEEP_RUNNING=1
        ;;
      --stop-existing)
        STOP_EXISTING=1
        ;;
      *)
        echo "[llm-check] Неизвестный аргумент: $arg" >&2
        echo "[llm-check] Используйте --help для справки." >&2
        exit 1
        ;;
    esac
  done
fi

require_command() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    return 0
  fi
  echo "[llm-check] Требуемая команда '$command_name' не найдена." >&2
  exit 1
}

cleanup() {
  local exit_code=$?
  if [[ "$KEEP_RUNNING" = "1" ]]; then
    echo "[llm-check] --keep-running активен, стек не останавливаю."
    exit "$exit_code"
  fi
  if [[ -n "$START_PID" ]] && kill -0 "$START_PID" 2>/dev/null; then
    echo "[llm-check] Останавливаю start.sh (PID $START_PID) ..."
    kill -TERM "$START_PID" 2>/dev/null || true
    wait "$START_PID" 2>/dev/null || true
  fi
  exit "$exit_code"
}

find_vllm_container() {
  if [[ "$LLM_SERVICE_RUNTIME" != "vllm" ]]; then
    return 0
  fi
  docker ps --filter "ancestor=${VLLM_IMAGE}" --format '{{.Names}}' | head -n 1
}

list_vllm_containers() {
  if [[ "$LLM_SERVICE_RUNTIME" != "vllm" ]]; then
    return 0
  fi
  docker ps --filter "ancestor=${VLLM_IMAGE}" --format '{{.Names}}'
}

print_stage() {
  local message="$1"
  echo "[llm-check][stage] $message"
}

handle_existing_vllm_containers() {
  if [[ "$LLM_SERVICE_RUNTIME" != "vllm" ]]; then
    return 0
  fi
  local existing_containers=()
  mapfile -t existing_containers < <(list_vllm_containers)

  if [[ "${#existing_containers[@]}" -eq 0 ]]; then
    return 0
  fi

  if [[ "$STOP_EXISTING" = "1" ]]; then
    print_stage "Останавливаю уже запущенные vLLM-контейнеры: ${existing_containers[*]}"
    docker stop "${existing_containers[@]}" >/dev/null
    return 0
  fi

  echo "[llm-check] Уже запущены vLLM-контейнеры: ${existing_containers[*]}" >&2
  echo "[llm-check] Они могут занимать VRAM и вызывать ложный OOM на старте." >&2
  echo "[llm-check] Останови их вручную: docker stop ${existing_containers[*]}" >&2
  echo "[llm-check] Или запусти helper так: bash scripts/run_llm_stage_check.sh --stop-existing" >&2
  exit 1
}

ensure_llama_cpp_assets() {
  if [[ "$LLM_SERVICE_RUNTIME" != "llama_cpp" ]]; then
    return 0
  fi

  require_command docker
  require_command huggingface-cli

  mkdir -p "$LLAMA_CPP_MODEL_DIR"

  if [[ ! -f "$LLAMA_CPP_MODEL_DIR/$LLAMA_CPP_MODEL_FILE" ]]; then
    print_stage "Докачиваю GGUF: ${LLAMA_CPP_MODEL_REPO}/${LLAMA_CPP_MODEL_FILE}"
    huggingface-cli download \
      "$LLAMA_CPP_MODEL_REPO" \
      "$LLAMA_CPP_MODEL_FILE" \
      --local-dir "$LLAMA_CPP_MODEL_DIR"
  else
    print_stage "GGUF уже найден: $LLAMA_CPP_MODEL_DIR/$LLAMA_CPP_MODEL_FILE"
  fi

  print_stage "Подтягиваю образ $LLAMA_CPP_DOCKER_IMAGE"
  docker pull "$LLAMA_CPP_DOCKER_IMAGE"
}

dump_diagnostics() {
  local container_name="${1:-}"
  {
    echo "===== $(date -Iseconds) ====="
    echo "cwd: $ROOT_DIR"
    echo "gateway_url: $GATEWAY_URL"
    echo "start_log: $START_LOG"
    echo "sse_log: $SSE_LOG"
    echo "docker_ps:"
    if command -v docker >/dev/null 2>&1; then
      docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' || true
    else
      echo "docker unavailable"
    fi
    echo
    echo "health_checks:"
    curl -sS -m 5 "$GATEWAY_URL/api/system/health" || true
    echo
    curl -sS -m 5 "http://127.0.0.1:8000/health" || true
    echo
    echo "start_log_tail:"
    tail -n 120 "$START_LOG" 2>/dev/null || true
    if [[ -n "$container_name" ]]; then
      echo
      echo "vllm_container: $container_name"
      echo "vllm_container_top:"
      docker top "$container_name" -eo pid,ppid,pcpu,pmem,etime,args 2>/dev/null || true
      echo
      echo "vllm_container_logs:"
      docker logs --tail 200 "$container_name" 2>&1 || true
    fi
    echo
    echo "llama_server_processes:"
    pgrep -fa '(^|/)llama-server([[:space:]]|$)' || true
    if [[ -f "$SSE_LOG" ]]; then
      echo
      echo "sse_log:"
      cat "$SSE_LOG"
    fi
    echo
  } | tee -a "$DIAG_LOG"
}

wait_for_http_ready() {
  local label="$1"
  local url="$2"
  local timeout_seconds="$3"
  local deadline=$((SECONDS + timeout_seconds))
  local next_heartbeat=$((SECONDS + HEARTBEAT_SECONDS))
  local container_name=""

  while [[ "$SECONDS" -lt "$deadline" ]]; do
    if [[ -n "$START_PID" ]] && ! kill -0 "$START_PID" 2>/dev/null; then
      echo "[llm-check] start.sh завершился раньше готовности gateway. Проверь лог: $START_LOG" >&2
      container_name="$(find_vllm_container || true)"
      dump_diagnostics "$container_name"
      return 1
    fi
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    if [[ "$SECONDS" -ge "$next_heartbeat" ]]; then
      container_name="$(find_vllm_container || true)"
      print_stage "$label ещё не готов ($((${deadline} - ${SECONDS}))s до таймаута); container=${container_name:-not-started}"
      tail -n 5 "$START_LOG" 2>/dev/null || true
      next_heartbeat=$((SECONDS + HEARTBEAT_SECONDS))
    fi
    sleep 2
  done

  echo "[llm-check] Таймаут ожидания ready endpoint: $url" >&2
  container_name="$(find_vllm_container || true)"
  dump_diagnostics "$container_name"
  return 1
}

wait_for_gateway_warmup_ready() {
  local timeout_seconds="$1"
  local deadline=$((SECONDS + timeout_seconds))
  local next_heartbeat=$((SECONDS + HEARTBEAT_SECONDS))
  local warmup_payload=""
  local container_name=""

  while [[ "$SECONDS" -lt "$deadline" ]]; do
    if [[ -n "$START_PID" ]] && ! kill -0 "$START_PID" 2>/dev/null; then
      echo "[llm-check] start.sh завершился раньше готовности warmup endpoint. Проверь лог: $START_LOG" >&2
      container_name="$(find_vllm_container || true)"
      dump_diagnostics "$container_name"
      return 1
    fi

    set +e
    warmup_payload="$(curl -fsS "$GATEWAY_URL/api/system/warmup")"
    local status=$?
    set -e
    if [[ "$status" -eq 0 ]]; then
      if python3 - "$warmup_payload" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
raise SystemExit(0 if payload.get("ready") is True else 1)
PY
      then
        echo "[llm-check] Gateway warmup готов: $warmup_payload"
        return 0
      fi
    fi

    if [[ "$SECONDS" -ge "$next_heartbeat" ]]; then
      print_stage "gateway warmup ещё не ready ($((${deadline} - ${SECONDS}))s до таймаута)"
      if [[ -n "$warmup_payload" ]]; then
        echo "[llm-check] warmup payload: $warmup_payload"
      fi
      next_heartbeat=$((SECONDS + HEARTBEAT_SECONDS))
    fi
    sleep 2
  done

  echo "[llm-check] Таймаут ожидания gateway warmup ready." >&2
  container_name="$(find_vllm_container || true)"
  dump_diagnostics "$container_name"
  return 1
}

require_command curl
require_command python3
if [[ "$LLM_SERVICE_RUNTIME" = "vllm" ]]; then
  require_command docker
fi

trap cleanup EXIT INT TERM

mkdir -p "$(dirname "$START_LOG")"
mkdir -p "$LOG_DIR"
rm -f "$SSE_LOG" "$DIAG_LOG"

handle_existing_vllm_containers
ensure_llama_cpp_assets

if [[ "$LLM_SERVICE_RUNTIME" = "vllm" ]]; then
  print_stage "Подтягиваю образ $VLLM_IMAGE"
  docker pull "$VLLM_IMAGE"
else
  print_stage "Использую LLM runtime: $LLM_SERVICE_RUNTIME"
fi

print_stage "Запускаю стек через start.sh"
LLM_SERVICE_ENABLED=true \
LLM_SERVICE_RUNTIME="$LLM_SERVICE_RUNTIME" \
LLM_SERVICE_EXECUTABLE="$ROOT_DIR/scripts/llama_server_docker.sh" \
LLM_SERVICE_MODEL_PATH="$LLAMA_CPP_MODEL_DIR/$LLAMA_CPP_MODEL_FILE" \
THIRD_PASS_LLM_TIMEOUT_MS="${THIRD_PASS_LLM_TIMEOUT_MS:-}" \
GATEWAY_JOB_TTL_MS="${GATEWAY_JOB_TTL_MS:-}" \
bash start.sh >"$START_LOG" 2>&1 &
START_PID="$!"
echo "[llm-check] start.sh PID: $START_PID"
echo "[llm-check] Лог старта: $START_LOG"
echo "[llm-check] SSE лог: $SSE_LOG"
echo "[llm-check] Диагностика: $DIAG_LOG"

print_stage "Жду готовности gateway"
wait_for_http_ready "gateway" "$GATEWAY_URL/api/system/health" "$START_TIMEOUT_SECONDS"
echo "[llm-check] Gateway готов: $GATEWAY_URL"
print_stage "Жду готовности gateway warmup"
wait_for_gateway_warmup_ready "$START_TIMEOUT_SECONDS"

print_stage "Создаю parse job"
JOB_ID="$(python3 - "$GATEWAY_URL" "$TEXT" <<'PY'
import json
import sys
import urllib.request

gateway_url = sys.argv[1].rstrip("/")
text = sys.argv[2]

payload = json.dumps({
    "text": text,
    "sync": False,
    "third_pass_enabled": True,
    "think_mode": False,
}).encode("utf-8")

request = urllib.request.Request(
    f"{gateway_url}/api/parse",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(request, timeout=30) as response:
    body = json.loads(response.read().decode("utf-8"))

print(body["job_id"])
PY
)"

echo "[llm-check] job_id: $JOB_ID"

print_stage "Читаю SSE stream"
if ! curl -fsS -N "$GATEWAY_URL/api/parse/jobs/$JOB_ID/stream" | tee "$SSE_LOG"; then
  dump_diagnostics "$(find_vllm_container || true)"
  exit 1
fi

echo
echo "[llm-check] Проверяю события stage_progress ..."
if ! python3 - "$SSE_LOG" <<'PY'
import json
import os
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_text(encoding="utf-8")
events = []
for chunk in raw.split("\n\n"):
    chunk = chunk.strip()
    if not chunk.startswith("data:"):
        continue
    payload = chunk[len("data:"):].strip()
    events.append(json.loads(payload))

nlp_seen = any(
    event.get("type") == "stage_progress"
    and event.get("stage") == "nlp"
    and event.get("status") in {"done", "error"}
    for event in events
)
llm_seen = any(
    event.get("type") == "stage_progress"
    and event.get("stage") == "llm"
    and event.get("status") in {"done", "error"}
    for event in events
)
result_event = next((event for event in events if event.get("type") == "result"), None)
occurrences = []
if isinstance(result_event, dict):
    summary = result_event.get("summary")
    if isinstance(summary, dict):
        third_pass_summary = summary.get("third_pass_summary")
        if isinstance(third_pass_summary, dict):
            raw_occurrences = third_pass_summary.get("occurrences")
            if isinstance(raw_occurrences, list):
                occurrences = [item for item in raw_occurrences if isinstance(item, dict)]

print("[llm-check] events:")
for event in events:
    print(json.dumps(event, ensure_ascii=False))

if not nlp_seen or not llm_seen:
    missing = []
    if not nlp_seen:
      missing.append("nlp")
    if not llm_seen:
      missing.append("llm")
    raise SystemExit(f"[llm-check] Не найдены stage_progress события для: {', '.join(missing)}")

require_occurrences = os.getenv("LLM_STAGE_CHECK_REQUIRE_THIRD_PASS_OCCURRENCES", "").strip().lower() in {
    "1", "true", "yes", "on"
}
expected_types = [
    item.strip()
    for item in os.getenv("LLM_STAGE_CHECK_EXPECT_TYPES", "").split(",")
    if item.strip()
]
expected_forms = [
    item.strip().lower()
    for item in os.getenv("LLM_STAGE_CHECK_EXPECT_FORMS", "").split(",")
    if item.strip()
]

if require_occurrences and not occurrences:
    raise SystemExit("[llm-check] third_pass_summary.occurrences пустой.")

if occurrences:
    print("[llm-check] third-pass occurrences:")
    for occurrence in occurrences:
        print(json.dumps(occurrence, ensure_ascii=False))

found_types = {str(item.get("expression_type", "")).strip().lower() for item in occurrences}
for expected_type in expected_types:
    if expected_type.lower() not in found_types:
        raise SystemExit(f"[llm-check] Не найден expected expression_type: {expected_type}")

found_forms = {
    str(item.get("canonical_form", "")).strip().lower()
    for item in occurrences
}.union({
    str(item.get("surface", "")).strip().lower()
    for item in occurrences
})
for expected_form in expected_forms:
    if expected_form not in found_forms:
        raise SystemExit(f"[llm-check] Не найдена expected form: {expected_form}")

print("[llm-check] OK: stage_progress для nlp и llm найдены.")
PY
then
  dump_diagnostics "$(find_vllm_container || true)"
  exit 1
fi

echo "[llm-check] Проверка завершена."
echo "[llm-check] Если нужен разбор, пришли мне файлы:"
echo "[llm-check]   $START_LOG"
echo "[llm-check]   $SSE_LOG"
echo "[llm-check]   $DIAG_LOG"
