# Agents Summary - Cycle 1

## Назначение
`AGENTS.md` — главный policy-документ для OpenAI Codex (автозагружается).
`CLAUDE.md` — эквивалент для Claude Code / Anthropic агентов (автозагружается).
Этот файл (`docs/agents.md`) содержит краткую операторскую выжимку и должен оставаться синхронизированным с `AGENTS.md`.

## Обязательный порядок
1. Перед mutating-задачей прочитать `AGENTS.md`, `MEMORY.md`, `CONTINUITY.md`, `docs/LLM_PROJECT_MAP.md`.
2. После архитектурного или процессного решения обновить `MEMORY.md`.
3. После завершённого mutating-шага или контрольной точки обновить `CONTINUITY.md`.
4. Если команда пользователя противоречит policy или решениям из `MEMORY.md`, остановиться и поднять конфликт.

## Язык и безопасность
- Ответы агента и новые комментарии в коде писать на русском языке.
- Существующие английские docstring и комментарии массово не переводить.
- Секреты хранить только в `.env` и `.env.*.local`.
- `.env.example` и `.env.*.example` использовать только как шаблоны.

## Рабочий цикл
`read -> do -> log -> save`

## Runtime quick reference
- `start.sh` остаётся единой точкой запуска локального стека.
- Реализация launcher разнесена по `scripts/start/helpers.sh`, `scripts/start/commands.sh`, `scripts/start/runtime.sh`.
- При изменениях bootstrap/runtime launcher сначала синхронизировать документацию агента и затем проверять `bash -n` и `./start.sh --print-config`.

## Маркеры аудита
### Policy markers
- `validation_blocked_high_confidence_trf`
- `validation_suspicious_trf_uncertain`
- `validation_second_pass_empty_fallback`
- `validation_no_trf_signal_fallback`
- `validation_trf_not_uncertain`

### Assignment markers
- `AssignmentSqliteStore`
- `assignments.db`
- `assignment_sync_use_case`
- `sync -> scan`

### SLA markers
- `p95 <= 1.2s`
- `p95 <= 200ms`
