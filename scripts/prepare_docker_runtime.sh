#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_RUNTIME_REQUIREMENTS_FILE="${PYTHON_RUNTIME_REQUIREMENTS_FILE:-requirements.compose.txt}"
PYTHON_RUNTIME_IMAGE_TAG="${PYTHON_RUNTIME_IMAGE_TAG:-local}"
NODE_RUNTIME_IMAGE_TAG="${NODE_RUNTIME_IMAGE_TAG:-local}"
# Собрать ROCm GPU-образ: передать --rocm чтобы включить сборку
BUILD_ROCM_IMAGE="${BUILD_ROCM_IMAGE:-0}"
PYTORCH_ROCM_VERSION="${PYTORCH_ROCM_VERSION:-rocm6.2}"

resolve_compose_command() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
    return 0
  fi
  echo "[prepare] Docker Compose is required."
  exit 1
}

for arg in "$@"; do
  case "$arg" in
    --rocm) BUILD_ROCM_IMAGE=1 ;;
    --help)
      echo "Использование: $0 [--rocm]"
      echo "  --rocm  Дополнительно собрать GPU-образ vocabulary-python-runtime-rocm"
      echo "          (требует интернет для скачивания PyTorch ROCm + моделей ~3 GB)"
      exit 0
      ;;
  esac
done

COMPOSE_CMD=()
resolve_compose_command

echo "[prepare] Pulling postgres:16 ..."
docker pull postgres:16

echo "[prepare] Building vocabulary-python-runtime:${PYTHON_RUNTIME_IMAGE_TAG} ..."
docker build \
  --build-arg "PYTHON_RUNTIME_REQUIREMENTS_FILE=${PYTHON_RUNTIME_REQUIREMENTS_FILE}" \
  -f docker/Dockerfile.python-runtime \
  -t "vocabulary-python-runtime:${PYTHON_RUNTIME_IMAGE_TAG}" \
  .

echo "[prepare] Building vocabulary-node-runtime:${NODE_RUNTIME_IMAGE_TAG} ..."
docker build \
  -f docker/Dockerfile.node-runtime \
  -t "vocabulary-node-runtime:${NODE_RUNTIME_IMAGE_TAG}" \
  .

if [ "${BUILD_ROCM_IMAGE}" = "1" ]; then
  echo "[prepare] Building vocabulary-python-runtime-rocm:${PYTHON_RUNTIME_IMAGE_TAG} ..."
  echo "[prepare] Это может занять 10–30 минут (PyTorch ROCm + spaCy en_core_web_trf + SBERT)"
  docker build \
    --build-arg "PYTORCH_ROCM_VERSION=${PYTORCH_ROCM_VERSION}" \
    -f docker/Dockerfile.python-runtime-rocm \
    -t "vocabulary-python-runtime-rocm:${PYTHON_RUNTIME_IMAGE_TAG}" \
    .
  echo "[prepare] vocabulary-python-runtime-rocm: готов."
fi

echo "[prepare] Validating docker compose configuration ..."
"${COMPOSE_CMD[@]}" config >/dev/null

echo "[prepare] Runtime images are ready."
