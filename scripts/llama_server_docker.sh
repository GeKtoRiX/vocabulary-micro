#!/usr/bin/env bash
set -euo pipefail

IMAGE="${LLAMA_CPP_DOCKER_IMAGE:-ghcr.io/ggml-org/llama.cpp:server}"

model_path=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  if [[ "${args[$i]}" == "--model" ]] && ((i + 1 < ${#args[@]})); then
    model_path="${args[$((i + 1))]}"
    break
  fi
done

if [[ -z "$model_path" ]]; then
  echo "[llama-server-docker] --model is required." >&2
  exit 1
fi

if [[ ! -f "$model_path" ]]; then
  echo "[llama-server-docker] model not found: $model_path" >&2
  exit 1
fi

model_dir="$(cd "$(dirname "$model_path")" && pwd)"

exec docker run --rm --network host \
  -v "$model_dir:$model_dir:ro" \
  "$IMAGE" \
  "$@"
