#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load nvm if available
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

BUILD_FRONTEND=false
DEV_MODE=false
SERVICES_READY=false
POSTGRES_MODE=0
PRINT_CONFIG=false
EXTRA_ENV_FILE="${START_ENV_FILE:-}"

PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT

load_env_defaults_file() {
  local file_path="$1"
  local line key
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
    if [ -n "${!key+x}" ]; then
      continue
    fi
    eval "export ${line}"
  done < "$file_path"
}

for arg in "$@"; do
  case "$arg" in
    --build)  BUILD_FRONTEND=true ;;
    --dev)    DEV_MODE=true ;;
    --postgres) POSTGRES_MODE=1 ;;
    --print-config) PRINT_CONFIG=true ;;
    --help)
      echo "Usage: $0 [--build] [--dev] [--postgres] [--print-config]"
      echo "  --build   Build frontend before starting server"
      echo "  --dev     Start Vite dev server instead of serving built files"
      echo "  --postgres  Run owner services on Postgres using OWNER_SERVICES_* defaults"
      echo "  --print-config  Print resolved runtime config and exit"
      exit 0
      ;;
  esac
done

load_env_defaults_file "$SCRIPT_DIR/.env"
load_env_defaults_file "$SCRIPT_DIR/.env.local"
if [ -n "$EXTRA_ENV_FILE" ]; then
  if [[ "$EXTRA_ENV_FILE" != /* ]]; then
    EXTRA_ENV_FILE="$SCRIPT_DIR/$EXTRA_ENV_FILE"
  fi
  load_env_defaults_file "$EXTRA_ENV_FILE"
fi
if [ "$POSTGRES_MODE" = "1" ] || [ "${POSTGRES_MODE:-0}" = "1" ]; then
  POSTGRES_MODE=1
  load_env_defaults_file "$SCRIPT_DIR/.env.postgres"
  load_env_defaults_file "$SCRIPT_DIR/.env.postgres.local"
fi
POSTGRES_MODE="${POSTGRES_MODE:-0}"

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

LEXICON_STORAGE_BACKEND="${LEXICON_STORAGE_BACKEND:-$OWNER_SERVICES_STORAGE_BACKEND}"
LEXICON_POSTGRES_URL="${LEXICON_POSTGRES_URL:-$OWNER_SERVICES_POSTGRES_URL}"
LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE="${LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE:-$OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE}"
LEXICON_POSTGRES_SCHEMA="${LEXICON_POSTGRES_SCHEMA:-lexicon}"
ASSIGNMENTS_STORAGE_BACKEND="${ASSIGNMENTS_STORAGE_BACKEND:-$OWNER_SERVICES_STORAGE_BACKEND}"
ASSIGNMENTS_POSTGRES_URL="${ASSIGNMENTS_POSTGRES_URL:-$OWNER_SERVICES_POSTGRES_URL}"
ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE="${ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE:-$OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE}"
ASSIGNMENTS_POSTGRES_SCHEMA="${ASSIGNMENTS_POSTGRES_SCHEMA:-assignments}"

if [ "$OWNER_SERVICES_STORAGE_BACKEND" = "postgres" ]; then
  echo "[start] Owner services storage backend: postgres"
fi

if $PRINT_CONFIG; then
  cat <<EOF
POSTGRES_MODE=$POSTGRES_MODE
GATEWAY_PARSE_BACKEND=$GATEWAY_PARSE_BACKEND
GATEWAY_LEXICON_BACKEND=$GATEWAY_LEXICON_BACKEND
GATEWAY_ASSIGNMENTS_BACKEND=$GATEWAY_ASSIGNMENTS_BACKEND
GATEWAY_STATISTICS_BACKEND=$GATEWAY_STATISTICS_BACKEND
GATEWAY_EXPORT_BACKEND=$GATEWAY_EXPORT_BACKEND
OWNER_SERVICES_STORAGE_BACKEND=$OWNER_SERVICES_STORAGE_BACKEND
OWNER_SERVICES_POSTGRES_URL=$OWNER_SERVICES_POSTGRES_URL
OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE=$OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE
LEXICON_STORAGE_BACKEND=$LEXICON_STORAGE_BACKEND
LEXICON_POSTGRES_URL=$LEXICON_POSTGRES_URL
LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE=$LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE
LEXICON_POSTGRES_SCHEMA=$LEXICON_POSTGRES_SCHEMA
ASSIGNMENTS_STORAGE_BACKEND=$ASSIGNMENTS_STORAGE_BACKEND
ASSIGNMENTS_POSTGRES_URL=$ASSIGNMENTS_POSTGRES_URL
ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE=$ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE
ASSIGNMENTS_POSTGRES_SCHEMA=$ASSIGNMENTS_POSTGRES_SCHEMA
EOF
  exit 0
fi

if $DEV_MODE; then
  echo "[start] Starting Vite dev server in background..."
  cd frontend && npm run dev &
  PIDS+=("$!")
  cd "$SCRIPT_DIR"
  echo "[start] Vite PID: ${PIDS[${#PIDS[@]}-1]}"
fi

if $BUILD_FRONTEND; then
  echo "[start] Building frontend..."
  cd frontend && npm run build
  cd "$SCRIPT_DIR"
  echo "[start] Frontend build complete."
fi

if [ ! -d backend/services/node_modules ]; then
  echo "[start] Installing service workspace dependencies..."
  cd backend/services && npm install
  cd "$SCRIPT_DIR"
fi

if ! $DEV_MODE && [ ! -d frontend/dist ]; then
  echo "[start] Built frontend not found; enabling gateway static build..."
  cd frontend && npm run build
  cd "$SCRIPT_DIR"
fi

echo "[start] Starting NLP capability service on http://${NLP_SERVICE_HOST}:${NLP_SERVICE_PORT} ..."
LEXICON_SERVICE_HOST="$LEXICON_SERVICE_HOST" \
LEXICON_SERVICE_PORT="$LEXICON_SERVICE_PORT" \
NLP_SERVICE_HOST="$NLP_SERVICE_HOST" \
NLP_SERVICE_PORT="$NLP_SERVICE_PORT" \
python3 -m backend.python_services.nlp_service.main &
PIDS+=("$!")

echo "[start] Starting export capability service on http://${EXPORT_SERVICE_HOST}:${EXPORT_SERVICE_PORT} ..."
LEXICON_SERVICE_HOST="$LEXICON_SERVICE_HOST" \
LEXICON_SERVICE_PORT="$LEXICON_SERVICE_PORT" \
EXPORT_SERVICE_HOST="$EXPORT_SERVICE_HOST" \
EXPORT_SERVICE_PORT="$EXPORT_SERVICE_PORT" \
python3 -m backend.python_services.export_service.main &
PIDS+=("$!")

echo "[start] Starting lexicon service on http://${LEXICON_SERVICE_HOST}:${LEXICON_SERVICE_PORT} ..."
(
  export LEXICON_SERVICE_HOST LEXICON_SERVICE_PORT
  export OWNER_SERVICES_STORAGE_BACKEND OWNER_SERVICES_POSTGRES_URL OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE
  export LEXICON_STORAGE_BACKEND LEXICON_POSTGRES_URL LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE LEXICON_POSTGRES_SCHEMA
  cd backend/services
  npm --workspace @vocabulary/lexicon-service run dev
) &
PIDS+=("$!")

echo "[start] Starting assignments service on http://${ASSIGNMENTS_SERVICE_HOST}:${ASSIGNMENTS_SERVICE_PORT} ..."
(
  export ASSIGNMENTS_SERVICE_HOST ASSIGNMENTS_SERVICE_PORT
  export OWNER_SERVICES_STORAGE_BACKEND OWNER_SERVICES_POSTGRES_URL OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE
  export ASSIGNMENTS_STORAGE_BACKEND ASSIGNMENTS_POSTGRES_URL ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE ASSIGNMENTS_POSTGRES_SCHEMA
  cd backend/services
  npm --workspace @vocabulary/assignments-service run dev
) &
PIDS+=("$!")

echo "[start] Starting gateway on http://${GATEWAY_HOST}:${GATEWAY_PORT} ..."
(
  export GATEWAY_HOST GATEWAY_PORT NLP_SERVICE_HOST NLP_SERVICE_PORT
  export EXPORT_SERVICE_HOST EXPORT_SERVICE_PORT LEXICON_SERVICE_HOST LEXICON_SERVICE_PORT
  export ASSIGNMENTS_SERVICE_HOST ASSIGNMENTS_SERVICE_PORT
  export GATEWAY_PARSE_BACKEND GATEWAY_LEXICON_BACKEND GATEWAY_ASSIGNMENTS_BACKEND
  export GATEWAY_STATISTICS_BACKEND GATEWAY_EXPORT_BACKEND
  if $DEV_MODE; then
    export GATEWAY_SERVE_STATIC=0
  fi
  cd backend/services
  npm --workspace @vocabulary/api-gateway run dev
) &
PIDS+=("$!")

wait "${PIDS[${#PIDS[@]}-1]}"
