#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

MODE="host"
PYTEST_TARGET="tests/backend/integration/test_postgres_cutover_smoke.py"
PYTEST_ARGS=()

print_help() {
  cat <<'EOF'
Использование:
  bash scripts/run_docker_smoke.sh [--host|--compose] [--test <pytest-node>] [-- <extra pytest args>]

Режимы:
  --host     Запустить docker smoke через pytest и локальный start.sh --postgres.
             По умолчанию используется:
             RUN_DOCKER_SMOKE=1 python3 -m pytest -q tests/backend/integration/test_postgres_cutover_smoke.py

  --compose  Запустить compose smoke-скрипт CI:
             bash .github/scripts/compose_postgres_smoke.sh

Опции:
  --test <node>
      Переопределить pytest target в режиме --host.
      Примеры:
        --test tests/backend/integration/test_postgres_cutover_smoke.py
        --test tests/backend/integration/test_postgres_cutover_smoke.py::test_statistics_composition

  --help
      Показать эту справку.

Примеры:
  bash scripts/run_docker_smoke.sh
  bash scripts/run_docker_smoke.sh --test tests/backend/integration/test_postgres_cutover_smoke.py::test_postgres_cutover_smoke
  bash scripts/run_docker_smoke.sh --host -- -k statistics -x
  bash scripts/run_docker_smoke.sh --compose
EOF
}

while (($# > 0)); do
  case "$1" in
    --host)
      MODE="host"
      shift
      ;;
    --compose)
      MODE="compose"
      shift
      ;;
    --test)
      if (($# < 2)); then
        echo "[smoke] --test требует значение" >&2
        exit 1
      fi
      PYTEST_TARGET="$2"
      shift 2
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    --)
      shift
      PYTEST_ARGS=("$@")
      break
      ;;
    *)
      echo "[smoke] Неизвестный аргумент: $1" >&2
      echo "[smoke] Используйте --help для справки." >&2
      exit 1
      ;;
  esac
done

has_direct_docker_access() {
  docker ps >/dev/null 2>&1
}

has_sg_docker_access() {
  sg docker -c 'docker ps' >/dev/null 2>&1
}

quote_args_for_shell() {
  local quoted=()
  local arg
  for arg in "$@"; do
    quoted+=("$(printf '%q' "$arg")")
  done
  printf '%s' "${quoted[*]}"
}

run_with_docker_access() {
  if has_direct_docker_access; then
    "$@"
    return
  fi

  if has_sg_docker_access; then
    local command
    command="$(quote_args_for_shell "$@")"
    echo "[smoke] direct docker access отсутствует, запускаю через sg docker"
    sg docker -c "$command"
    return
  fi

  echo "[smoke] Docker daemon недоступен ни напрямую, ни через sg docker." >&2
  echo "[smoke] После выдачи доступа повторите запуск." >&2
  exit 1
}

if [[ "$MODE" == "compose" ]]; then
  echo "[smoke] compose mode"
  run_with_docker_access bash .github/scripts/compose_postgres_smoke.sh
  exit 0
fi

echo "[smoke] host mode"
echo "[smoke] target: ${PYTEST_TARGET}"

HOST_COMMAND=(
  env
  RUN_DOCKER_SMOKE=1
  python3
  -m
  pytest
  -q
  "$PYTEST_TARGET"
)

if ((${#PYTEST_ARGS[@]} > 0)); then
  HOST_COMMAND+=("${PYTEST_ARGS[@]}")
fi

run_with_docker_access "${HOST_COMMAND[@]}"
