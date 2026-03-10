#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-vocabulary-ci-${GITHUB_RUN_ID:-local}-$$}"
export POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-55432}"
export LEGACY_BACKEND_HOST_PORT="${LEGACY_BACKEND_HOST_PORT:-58766}"
export NLP_SERVICE_HOST_PORT="${NLP_SERVICE_HOST_PORT:-58767}"
export EXPORT_SERVICE_HOST_PORT="${EXPORT_SERVICE_HOST_PORT:-58768}"
export LEXICON_SERVICE_HOST_PORT="${LEXICON_SERVICE_HOST_PORT:-54011}"
export ASSIGNMENTS_SERVICE_HOST_PORT="${ASSIGNMENTS_SERVICE_HOST_PORT:-54012}"
export GATEWAY_HOST_PORT="${GATEWAY_HOST_PORT:-58765}"
export PYTHON_RUNTIME_REQUIREMENTS_FILE="${PYTHON_RUNTIME_REQUIREMENTS_FILE:-requirements.compose.txt}"

docker_cmd() {
  if docker ps >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  if sg docker -c 'docker ps' >/dev/null 2>&1; then
    local quoted=()
    local arg
    for arg in "$@"; do
      quoted+=("$(printf '%q' "$arg")")
    done
    sg docker -c "docker ${quoted[*]}"
    return
  fi
  echo "[compose-smoke] docker daemon is not accessible" >&2
  return 1
}

cleanup() {
  docker_cmd compose down -v --remove-orphans >/dev/null 2>&1 || true
}

dump_logs() {
  echo "::group::docker compose ps"
  docker_cmd compose ps || true
  echo "::endgroup::"
  echo "::group::docker compose logs"
  docker_cmd compose logs || true
  echo "::endgroup::"
}

trap cleanup EXIT
trap 'dump_logs' ERR

echo "[compose-smoke] docker compose version"
docker_cmd compose version

echo "[compose-smoke] starting Postgres-first stack"
docker_cmd compose --env-file .env.compose.postgres.example up -d --remove-orphans

python3 - <<'PY'
import json
import os
import time
import urllib.request


def request_json(url: str, *, method: str = "GET", payload: dict | None = None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def wait_for_json(url: str, *, timeout: int = 420):
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            return request_json(url)
        except Exception as error:
            last_error = str(error)
            time.sleep(2)
    raise SystemExit(f"{url} did not become ready: {last_error}")


gateway_port = int(os.environ["GATEWAY_HOST_PORT"])
lexicon_port = int(os.environ["LEXICON_SERVICE_HOST_PORT"])
assignments_port = int(os.environ["ASSIGNMENTS_SERVICE_HOST_PORT"])
nlp_port = int(os.environ["NLP_SERVICE_HOST_PORT"])
export_port = int(os.environ["EXPORT_SERVICE_HOST_PORT"])

_, gateway_health = wait_for_json(f"http://127.0.0.1:{gateway_port}/api/system/health")
_, lexicon_health = wait_for_json(f"http://127.0.0.1:{lexicon_port}/health")
_, assignments_health = wait_for_json(f"http://127.0.0.1:{assignments_port}/health")
_, nlp_health = wait_for_json(f"http://127.0.0.1:{nlp_port}/internal/v1/system/health")
_, export_health = wait_for_json(f"http://127.0.0.1:{export_port}/internal/v1/system/health")

assert gateway_health["status"] == "ok"
assert lexicon_health["storage_backend"] == "postgres"
assert assignments_health["storage_backend"] == "postgres"
assert nlp_health["status"] == "ok"
assert export_health["status"] == "ok"

_, assignments = request_json(f"http://127.0.0.1:{gateway_port}/api/assignments")
assert len(assignments) >= 2

_, category_payload = request_json(
    f"http://127.0.0.1:{gateway_port}/api/lexicon/categories",
    method="POST",
    payload={"name": "Compose Smoke"},
)
assert "Compose Smoke" in category_payload["categories"]

_, entry_payload = request_json(
    f"http://127.0.0.1:{gateway_port}/api/lexicon/entries",
    method="POST",
    payload={
        "category": "Compose Smoke",
        "value": "composeprobe",
        "source": "manual",
        "confidence": 0.99,
    },
)
assert "composeprobe" in entry_payload["message"]

_, scan_start = request_json(
    f"http://127.0.0.1:{gateway_port}/api/assignments/scan",
    method="POST",
    payload={
        "title": "Compose Assignment Smoke",
        "content_original": "I walk in the park.",
        "content_completed": "I composeprobe swiftly in the park.",
    },
)
job_id = scan_start["job_id"]

request = urllib.request.Request(
    f"http://127.0.0.1:{gateway_port}/api/assignments/scan/jobs/{job_id}/stream",
    method="GET",
)
with urllib.request.urlopen(request, timeout=30) as response:
    stream = response.read().decode("utf-8")
assert '"type":"result"' in stream
assert "Compose Assignment Smoke" in stream

_, statistics = request_json(f"http://127.0.0.1:{gateway_port}/api/statistics")
assert statistics["overview"]["total_assignments"] >= 3
PY

POSTGRES_CONTAINER_ID="$(docker_cmd compose ps -q postgres)"
if [ -z "$POSTGRES_CONTAINER_ID" ]; then
  echo "[compose-smoke] postgres container not found" >&2
  exit 1
fi

echo "[compose-smoke] verifying migration bookkeeping in postgres"
docker_cmd exec "$POSTGRES_CONTAINER_ID" \
  psql -U postgres -d vocabulary -At -c \
  "select service_name || ':' || version from service_postgres_migrations order by service_name, version;" \
  | tee /tmp/compose-smoke-migrations.txt

grep -q '^assignments-service:0001_init$' /tmp/compose-smoke-migrations.txt
grep -q '^lexicon-service:0001_init$' /tmp/compose-smoke-migrations.txt

echo "[compose-smoke] success"
