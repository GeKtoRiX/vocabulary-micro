build_nlp_command() {
  local llm_base_url="$1" enable_llm="$2"
  local cmd=""
  if [ "${PYTHON_BACKEND}" = "docker" ]; then
    printf -v cmd \
      'exec docker run --rm --network host -v %q:/app -e LEXICON_SERVICE_HOST=%q -e LEXICON_SERVICE_PORT=%q -e NLP_SERVICE_HOST=%q -e NLP_SERVICE_PORT=%q -e BERT_DEVICE=%q -e BERT_MODEL_NAME=%q -e BERT_LOCAL_FILES_ONLY=true -e BERT_TIMEOUT_MS=%q -e ENABLE_THIRD_PASS_LLM=%q -e THIRD_PASS_LLM_BASE_URL=%q -e THIRD_PASS_LLM_MODEL=%q -e THIRD_PASS_LLM_TIMEOUT_MS=%q -e LLAMA_SERVER_AUTOSTART_ENABLED=false -e HSA_OVERRIDE_GFX_VERSION=%q -e TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=%q -e TOKENIZERS_PARALLELISM=false %s %q python3 -m backend.python_services.nlp_service.main' \
      "$SCRIPT_DIR" "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
      "$NLP_SERVICE_HOST" "$NLP_SERVICE_PORT" \
      "${BERT_DEVICE:-cpu}" "${BERT_MODEL_NAME:-string_similarity}" "${BERT_TIMEOUT_MS:-12000}" \
      "$enable_llm" "$llm_base_url" "$LLM_SERVICE_MODEL" "$THIRD_PASS_LLM_TIMEOUT_MS" \
      "${HSA_OVERRIDE_GFX_VERSION:-}" "${TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL:-0}" \
      "${PYTHON_DOCKER_GPU_FLAGS}" "$PYTHON_IMAGE"
  else
    printf -v cmd \
      'cd %q && exec env LEXICON_SERVICE_HOST=%q LEXICON_SERVICE_PORT=%q NLP_SERVICE_HOST=%q NLP_SERVICE_PORT=%q BERT_DEVICE=%q BERT_MODEL_NAME=%q BERT_LOCAL_FILES_ONLY=%q BERT_TIMEOUT_MS=%q ENABLE_THIRD_PASS_LLM=%q THIRD_PASS_LLM_BASE_URL=%q THIRD_PASS_LLM_MODEL=%q THIRD_PASS_LLM_TIMEOUT_MS=%q LLAMA_SERVER_AUTOSTART_ENABLED=false HSA_OVERRIDE_GFX_VERSION=%q TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=%q TOKENIZERS_PARALLELISM=false python3 -m backend.python_services.nlp_service.main' \
      "$SCRIPT_DIR" "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
      "$NLP_SERVICE_HOST" "$NLP_SERVICE_PORT" \
      "${BERT_DEVICE:-cpu}" "${BERT_MODEL_NAME:-string_similarity}" "${BERT_LOCAL_FILES_ONLY:-true}" \
      "${BERT_TIMEOUT_MS:-12000}" "$enable_llm" "$llm_base_url" "$LLM_SERVICE_MODEL" \
      "$THIRD_PASS_LLM_TIMEOUT_MS" "${HSA_OVERRIDE_GFX_VERSION:-}" "${TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL:-0}"
  fi
  printf '%s' "$cmd"
}

build_export_command() {
  local cmd=""
  if [ "${PYTHON_BACKEND}" = "docker" ]; then
    printf -v cmd \
      'exec docker run --rm --network host -v %q:/app -e LEXICON_SERVICE_HOST=%q -e LEXICON_SERVICE_PORT=%q -e EXPORT_SERVICE_HOST=%q -e EXPORT_SERVICE_PORT=%q -e TOKENIZERS_PARALLELISM=false %q python3 -m backend.python_services.export_service.main' \
      "$SCRIPT_DIR" "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
      "$EXPORT_SERVICE_HOST" "$EXPORT_SERVICE_PORT" "$PYTHON_IMAGE"
  else
    printf -v cmd \
      'cd %q && exec env LEXICON_SERVICE_HOST=%q LEXICON_SERVICE_PORT=%q EXPORT_SERVICE_HOST=%q EXPORT_SERVICE_PORT=%q python3 -m backend.python_services.export_service.main' \
      "$SCRIPT_DIR" "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
      "$EXPORT_SERVICE_HOST" "$EXPORT_SERVICE_PORT"
  fi
  printf '%s' "$cmd"
}

build_lexicon_command() {
  local cmd=""
  printf -v cmd \
    'cd %q && exec env LEXICON_SERVICE_HOST=%q LEXICON_SERVICE_PORT=%q OWNER_SERVICES_POSTGRES_URL=%q LEXICON_POSTGRES_URL=%q LEXICON_POSTGRES_SCHEMA=%q npm --workspace @vocabulary/lexicon-service run dev' \
    "$SCRIPT_DIR/backend/services" \
    "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
    "$OWNER_SERVICES_POSTGRES_URL" \
    "$LEXICON_POSTGRES_URL" "$LEXICON_POSTGRES_SCHEMA"
  printf '%s' "$cmd"
}

build_assignments_command() {
  local cmd=""
  printf -v cmd \
    'cd %q && exec env ASSIGNMENTS_SERVICE_HOST=%q ASSIGNMENTS_SERVICE_PORT=%q OWNER_SERVICES_POSTGRES_URL=%q ASSIGNMENTS_POSTGRES_URL=%q ASSIGNMENTS_POSTGRES_SCHEMA=%q npm --workspace @vocabulary/assignments-service run dev' \
    "$SCRIPT_DIR/backend/services" \
    "$ASSIGNMENTS_SERVICE_HOST" "$ASSIGNMENTS_SERVICE_PORT" \
    "$OWNER_SERVICES_POSTGRES_URL" \
    "$ASSIGNMENTS_POSTGRES_URL" "$ASSIGNMENTS_POSTGRES_SCHEMA"
  printf '%s' "$cmd"
}

build_gateway_command() {
  local cmd=""
  printf -v cmd \
    'cd %q && exec env GATEWAY_HOST=%q GATEWAY_PORT=%q NLP_SERVICE_HOST=%q NLP_SERVICE_PORT=%q EXPORT_SERVICE_HOST=%q EXPORT_SERVICE_PORT=%q LEXICON_SERVICE_HOST=%q LEXICON_SERVICE_PORT=%q ASSIGNMENTS_SERVICE_HOST=%q ASSIGNMENTS_SERVICE_PORT=%q GATEWAY_PARSE_BACKEND=%q GATEWAY_LEXICON_BACKEND=%q GATEWAY_ASSIGNMENTS_BACKEND=%q GATEWAY_STATISTICS_BACKEND=%q GATEWAY_EXPORT_BACKEND=%q GATEWAY_SERVE_STATIC=%q npm --workspace @vocabulary/api-gateway run dev' \
    "$SCRIPT_DIR/backend/services" \
    "$GATEWAY_HOST" "$GATEWAY_PORT" \
    "$NLP_SERVICE_HOST" "$NLP_SERVICE_PORT" \
    "$EXPORT_SERVICE_HOST" "$EXPORT_SERVICE_PORT" \
    "$LEXICON_SERVICE_HOST" "$LEXICON_SERVICE_PORT" \
    "$ASSIGNMENTS_SERVICE_HOST" "$ASSIGNMENTS_SERVICE_PORT" \
    "$GATEWAY_PARSE_BACKEND" "$GATEWAY_LEXICON_BACKEND" "$GATEWAY_ASSIGNMENTS_BACKEND" \
    "$GATEWAY_STATISTICS_BACKEND" "$GATEWAY_EXPORT_BACKEND" \
    "$([ "$DEV_MODE" = true ] && echo 0 || echo "${GATEWAY_SERVE_STATIC:-1}")"
  printf '%s' "$cmd"
}

build_llm_vllm_command() {
  local cmd=""
  printf -v cmd \
    'exec docker run --rm --network host -v %q:/root/.cache/huggingface -e HSA_OVERRIDE_GFX_VERSION=%q %s %q %q --host %q --port %q --quantization fp8 --max-model-len %q --gpu-memory-utilization %q --reasoning-parser qwen3' \
    "$HF_CACHE" "${HSA_OVERRIDE_GFX_VERSION:-11.0.0}" "${ROCM_DOCKER_GPU_FLAGS}" \
    "$VLLM_IMAGE" "$LLM_SERVICE_MODEL" \
    "$LLM_SERVICE_HOST" "$LLM_SERVICE_PORT" "$LLM_SERVICE_MAX_MODEL_LEN" "$LLM_SERVICE_GPU_UTIL"
  printf '%s' "$cmd"
}

build_llm_llama_command() {
  local executable_path model_path cmd=""
  executable_path="$(resolve_executable_for_managed_llm "$LLM_SERVICE_EXECUTABLE")"
  model_path="$(resolve_path_if_relative "$LLM_SERVICE_MODEL_PATH")"
  printf -v cmd \
    'exec %q --host %q --port %q --model %q --alias %q --ctx-size %q --n-gpu-layers %q --batch-size %q --ubatch-size %q --parallel %q --flash-attn %q' \
    "$executable_path" "$LLM_SERVICE_HOST" "$LLM_SERVICE_PORT" \
    "$model_path" "$LLM_SERVICE_MODEL" "$LLM_SERVICE_MAX_MODEL_LEN" "$LLM_SERVICE_N_GPU_LAYERS" \
    "$LLM_SERVICE_BATCH_SIZE" "$LLM_SERVICE_UBATCH_SIZE" "$LLM_SERVICE_PARALLEL_SLOTS" "$LLM_SERVICE_FLASH_ATTN"
  [ "${LLM_SERVICE_THREADS}" -gt 0 ] && printf -v cmd '%s --threads %q' "$cmd" "$LLM_SERVICE_THREADS"
  [ "${LLM_SERVICE_THREADS_BATCH}" -gt 0 ] && printf -v cmd '%s --threads-batch %q' "$cmd" "$LLM_SERVICE_THREADS_BATCH"
  [ "${LLM_SERVICE_THREADS_HTTP}" -gt 0 ] && printf -v cmd '%s --threads-http %q' "$cmd" "$LLM_SERVICE_THREADS_HTTP"
  [ "${LLM_SERVICE_CACHE_REUSE}" -gt 0 ] && printf -v cmd '%s --cache-reuse %q' "$cmd" "$LLM_SERVICE_CACHE_REUSE"
  [ "$LLM_SERVICE_DISABLE_WARMUP" = "true" ] && cmd="${cmd} --no-warmup"
  [ "$LLM_SERVICE_DISABLE_WEBUI" = "true" ] && cmd="${cmd} --no-webui"
  [ -n "$LLM_SERVICE_EXTRA_ARGS" ] && cmd="${cmd} ${LLM_SERVICE_EXTRA_ARGS}"
  printf '%s' "$cmd"
}

build_frontend_dev_command() {
  local cmd=""
  printf -v cmd 'cd %q && exec npm run dev -- --host %q --port %q --strictPort' \
    "$SCRIPT_DIR/frontend" "$FRONTEND_DEV_HOST" "$FRONTEND_DEV_PORT"
  printf '%s' "$cmd"
}
