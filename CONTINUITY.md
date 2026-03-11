# CONTINUITY.md

## Current Task
Managed `llama.cpp + GGUF` third-pass стабилизирован и подтверждён живым e2e smoke на phrasal verbs/idioms.

## Progress
100%

## Blocked by
Нет блокеров; следующий шаг зависит только от решения пользователя по merge/deploy.

## Next Step
При необходимости заново прогнать `bash scripts/run_llm_mwe_e2e.sh` для живой проверки `look into` / `spill the beans` / `carry out`.

## What Was Done
1. `start.sh` расширен managed LLM lifecycle:
   - добавлены `LLM_SERVICE_*`, `VLLM_IMAGE`, `HF_CACHE`
   - managed vLLM service стартует раньше NLP service и проверяется по `/health`
   - в NLP runtime принудительно прокидываются `ENABLE_THIRD_PASS_LLM`, `THIRD_PASS_LLM_BASE_URL`, `THIRD_PASS_LLM_MODEL`, `LLAMA_SERVER_AUTOSTART_ENABLED=false`
2. `api-gateway` parse-orchestration разделён на два шага:
   - первый вызов всегда делает `/internal/v1/nlp/parse` с `third_pass_enabled: false`
   - optional второй вызов идёт в `/internal/v1/nlp/third-pass`
   - в SSE добавлены `stage_progress` события для `nlp` и `llm`
   - ошибка LLM third-pass больше не роняет весь parse job
3. Фронтенд дополнен popup этапов:
   - `SSEEvent` и `useSSEJob` расширены под `stage_progress`
   - добавлен `frontend/src/components/StageProgressPopup.tsx`
   - `ParseTab` инициализирует/обновляет стадии и скрывает popup на `result/error`
4. Env-документация обновлена:
   - `.env.example` получил шаблон managed vLLM секции
   - локальный `.env` дополнен закомментированным LLM-блоком
5. Проверки:
   - `npm --prefix frontend run build` -> OK
   - `npm --prefix frontend test -- --run` -> OK
   - `npm --prefix backend/services test -- --run tests/backend/services/test_gateway_public_parity.test.ts tests/backend/services/test_gateway_e2e_all_features.test.ts tests/backend/services/test_gateway_failure_modes.test.ts` -> OK
   - `./start.sh --print-config` -> OK, LLM config печатается
6. Локальный `.env` переключён на `LLM_SERVICE_ENABLED=true`.
7. Попытка runtime-проверки начата:
   - `docker pull vllm/vllm-openai-rocm:latest` стартовал успешно и начал скачивание слоёв
   - по последнему наблюдаемому прогрессу основной слой дошёл примерно до `320 MB / 5.362 GB`
   - pull остановлен вручную, чтобы не оставлять скрытую долгую загрузку без присмотра
8. Добавлен helper `scripts/run_llm_stage_check.sh`:
   - сам делает `docker pull vllm/vllm-openai-rocm:latest`
   - поднимает стек через `bash start.sh` с `LLM_SERVICE_ENABLED=true`
   - запускает `POST /api/parse` с `third_pass_enabled=true`
   - печатает SSE stream и валится, если не находит `stage_progress` для `nlp` и `llm`
   - проверка `bash -n` и `--help` прошла успешно
9. `start.sh` получил `LLM_SERVICE_READY_TIMEOUT_SECONDS` (default `900`) вместо жёсткого LLM readiness timeout `300s`, чтобы cold start ROCm/vLLM не обрывался раньше времени.
10. `scripts/run_llm_stage_check.sh` усилен для ручной диагностики:
   - добавлены heartbeat-сообщения по этапам ожидания
   - raw SSE сохраняется в отдельный лог
   - при сбое автоматически собирается диагностический dump (`docker ps`, health-checks, `tail` start log, `docker logs/top` для vLLM)
   - добавлен флаг `--keep-running`, если нужно оставить стек после проверки
11. Исправлен регресс в `scripts/run_llm_stage_check.sh`: вызов `wait_for_http_ready` переведён на новую сигнатуру `label + url + timeout`, из-за чего helper больше не падает с `unbound variable` на старте.
12. Runtime-диагностика показала, что текущий cold start `vLLM` падает не по timeout, а сначала по VRAM, а затем по аппаратно неподдерживаемому FP8 kernel path (`torch._scaled_mm ... ROCm MI300+`), поэтому local-first стратегия смещена на `llama.cpp + GGUF`.
13. `scripts/run_llm_stage_check.sh` теперь перед стартом проверяет уже запущенные контейнеры `vllm/vllm-openai-rocm:latest` и:
   - завершает запуск с явной подсказкой, если такие контейнеры найдены
   - умеет остановить их автоматически через `--stop-existing`
14. `start.sh` переведён на runtime-переключаемый managed LLM service:
   - добавлен `LLM_SERVICE_RUNTIME=llama_cpp|vllm`
   - local default переключён на `llama_cpp`
   - для `llama.cpp` добавлены `LLM_SERVICE_EXECUTABLE`, `LLM_SERVICE_MODEL_PATH`, `LLM_SERVICE_N_GPU_LAYERS` и связанные tuning env
   - readiness теперь проверяется через универсальный LLM probe (`/health` и `/v1/models`)
15. `.env.example`, `README.md` и `scripts/run_llm_stage_check.sh` обновлены под `llama.cpp` path:
   - helper больше не требует Docker/pull для `llama_cpp`
   - diagnostics умеют показывать `llama-server` процессы
   - shell syntax checks и `python3 -m pytest -q tests/backend/unit/infrastructure/bootstrap/test_llama_server_runtime.py tests/backend/unit/infrastructure/config/test_settings.py` прошли успешно
16. Локальный `.env` переключён на `llama.cpp` через docker-wrapper:
   - `LLM_SERVICE_RUNTIME=llama_cpp`
   - `LLM_SERVICE_EXECUTABLE=scripts/llama_server_docker.sh`
   - `LLM_SERVICE_MODEL_PATH=backend/python_services/infrastructure/runtime/models/lmstudio-community-Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf`
   - `LLM_SERVICE_N_GPU_LAYERS=0`, `LLM_SERVICE_THREADS=12`
17. Добавлен `scripts/llama_server_docker.sh`, который запускает официальный `ghcr.io/ggml-org/llama.cpp:server` и монтирует локальную директорию модели.
18. `scripts/run_llm_stage_check.sh` теперь в `llama_cpp`-режиме:
   - сам проверяет/докачивает `lmstudio-community/Qwen3.5-9B-GGUF` файл `Qwen3.5-9B-Q4_K_M.gguf`
   - сам подтягивает образ `ghcr.io/ggml-org/llama.cpp:server`
   - после этого поднимает стек и проверяет `stage_progress`
19. Найден и исправлен bootstrap bug в `start.sh`: `LLM_SERVICE_*` defaults выставлялись до чтения `.env`, из-за чего helper видел `LLM_SERVICE_EXECUTABLE=llama-server` вместо `scripts/llama_server_docker.sh`. Исправление состоит из двух частей:
   - `LLM_SERVICE_*` теперь получают defaults после `load_env_defaults_file`
   - `load_env_defaults_file` теперь заполняет пустые значения из `.env`, а не пропускает их только из-за факта существования переменной
20. После фикса `./start.sh --print-config` подтверждает корректный local `llama.cpp` runtime:
   - `LLM_SERVICE_EXECUTABLE=scripts/llama_server_docker.sh`
   - `LLM_SERVICE_MODEL_PATH=backend/python_services/infrastructure/runtime/models/lmstudio-community-Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf`
   - `LLM_SERVICE_N_GPU_LAYERS=0`
21. Live-smoke показал, что стек теперь реально доходит до:
   - `progress`
   - `stage_progress { stage: 'nlp', status: 'done' }`
   - затем уходит в долгий third-pass на `llama.cpp`
22. Найден ещё один semantic bug в gateway:
   - если `/internal/v1/nlp/third-pass` возвращал `200`, но payload внутри содержал `status: failed`, gateway всё равно публиковал `stage_progress { stage: 'llm', status: 'done' }`
   - теперь такой payload публикуется как `stage_progress { stage: 'llm', status: 'error' }` с сообщением из `stage_statuses[*].metadata.error`
   - покрыто тестом в `tests/backend/services/test_gateway_failure_modes.test.ts`
23. Временный hour-mode больше не нужен и удалён:
   - локальный runtime сведен к практическим значениям `THIRD_PASS_LLM_TIMEOUT_MS=300000` и `GATEWAY_JOB_TTL_MS=420000`
   - удалён helper `scripts/run_llm_stage_check_1h.sh`
24. Live-smoke подтвердил полный успешный цикл:
   - `progress`
   - `stage_progress { stage: 'nlp', status: 'done' }`
   - `stage_progress { stage: 'llm', status: 'done' }`
   - `result`
   - `done`
   - `third_pass_summary.status = 'ok'`
   - реальный `llm_extract` после fallback-парсинга reasoning-path занял около `64315 ms` на MWE smoke-тексте
   - `third_pass_summary.occurrences` содержит `look into`, `spill the beans`, `carry out`
25. `scripts/run_llm_stage_check.sh` теперь умеет не только проверять stage_progress, но и:
   - требовать непустой `third_pass_summary.occurrences`
   - валидировать ожидаемые `expression_type`
   - валидировать ожидаемые canonical forms
26. Добавлен `scripts/run_llm_stage_check_tuned.sh`:
   - экспортирует `THIRD_PASS_LLM_TIMEOUT_MS=300000`
   - экспортирует `GATEWAY_JOB_TTL_MS=420000`
   - запускает основной helper и является рекомендуемым smoke-entrypoint под текущую машину
27. Добавлен `scripts/run_llm_mwe_e2e.sh`:
   - использует текст с phrasal verb и idiom
   - требует `expression_type=phrasal_verb,idiom`
   - требует формы `look into`, `spill the beans`, `carry out`
   - служит живым end-to-end smoke для LLM-поиска MWE

## Last Updated
2026-03-11
