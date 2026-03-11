#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Практический профиль под текущую Qwen3.5-9B GGUF на этой машине:
# реальный third-pass занимает около 182 секунд, поэтому даём умеренный запас.
export THIRD_PASS_LLM_TIMEOUT_MS="${THIRD_PASS_LLM_TIMEOUT_MS:-300000}"
export GATEWAY_JOB_TTL_MS="${GATEWAY_JOB_TTL_MS:-420000}"

echo "[llm-check-tuned] THIRD_PASS_LLM_TIMEOUT_MS=${THIRD_PASS_LLM_TIMEOUT_MS}"
echo "[llm-check-tuned] GATEWAY_JOB_TTL_MS=${GATEWAY_JOB_TTL_MS}"

exec bash "$ROOT_DIR/scripts/run_llm_stage_check.sh" "$@"
