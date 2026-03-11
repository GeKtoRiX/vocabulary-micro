#!/usr/bin/env bash
set -euo pipefail

IMAGE="${LLAMA_CPP_DOCKER_IMAGE:-ghcr.io/ggml-org/llama.cpp:server-rocm}"

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

# GPU-флаги для AMD ROCm (добавляются только если /dev/kfd доступен)
gpu_flags=()
if [[ -e /dev/kfd ]]; then
  gpu_flags+=(--device=/dev/kfd)
  [[ -e /dev/dri ]] && gpu_flags+=(--device=/dev/dri)
  gpu_flags+=(--group-add video --group-add render)
fi

# HSA env для AMD RDNA (gfx1102 / RX 7600 XT и аналогичные)
hsa_env=()
[[ -n "${HSA_OVERRIDE_GFX_VERSION:-}" ]] && hsa_env+=(-e "HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION}")
[[ -n "${TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL:-}" ]] && hsa_env+=(-e "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=${TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL}")

exec docker run --rm --network host \
  "${gpu_flags[@]}" \
  "${hsa_env[@]}" \
  -v "$model_dir:$model_dir:ro" \
  "$IMAGE" \
  "$@"
