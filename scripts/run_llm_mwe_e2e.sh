#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

export THIRD_PASS_LLM_TIMEOUT_MS="${THIRD_PASS_LLM_TIMEOUT_MS:-300000}"
export GATEWAY_JOB_TTL_MS="${GATEWAY_JOB_TTL_MS:-420000}"
export LLM_STAGE_CHECK_TEXT="${LLM_STAGE_CHECK_TEXT:-Please look into the issue before you spill the beans during the meeting, then carry out the fix and call it a day.}"
export LLM_STAGE_CHECK_REQUIRE_THIRD_PASS_OCCURRENCES="${LLM_STAGE_CHECK_REQUIRE_THIRD_PASS_OCCURRENCES:-true}"
export LLM_STAGE_CHECK_EXPECT_TYPES="${LLM_STAGE_CHECK_EXPECT_TYPES:-phrasal_verb,idiom}"
export LLM_STAGE_CHECK_EXPECT_FORMS="${LLM_STAGE_CHECK_EXPECT_FORMS:-look into,spill the beans,carry out}"

echo "[llm-mwe-e2e] THIRD_PASS_LLM_TIMEOUT_MS=${THIRD_PASS_LLM_TIMEOUT_MS}"
echo "[llm-mwe-e2e] GATEWAY_JOB_TTL_MS=${GATEWAY_JOB_TTL_MS}"
echo "[llm-mwe-e2e] LLM_STAGE_CHECK_TEXT=${LLM_STAGE_CHECK_TEXT}"
echo "[llm-mwe-e2e] LLM_STAGE_CHECK_EXPECT_TYPES=${LLM_STAGE_CHECK_EXPECT_TYPES}"
echo "[llm-mwe-e2e] LLM_STAGE_CHECK_EXPECT_FORMS=${LLM_STAGE_CHECK_EXPECT_FORMS}"

exec bash "$ROOT_DIR/scripts/run_llm_stage_check.sh" "$@"
