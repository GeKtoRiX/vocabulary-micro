# CONTINUITY.md

## Current Task
Документация, агентская обвязка и README обновлены по итогам трёх циклов изменений:
FSD-миграция фронтенда, рефакторинг start.sh, E2E LLM smoke, Playwright UI smoke.

## Progress
100%

## Blocked by
Нет блокеров.

## Next Step
Следующая задача определяется пользователем. Возможные направления:
- расширение Playwright smoke (негативные сценарии, мобильный viewport)
- добавление CI workflow (GitHub Actions)
- новая функциональность

## What Was Done (последние циклы)

### FSD-миграция фронтенда (коммит b88b917)
1. `frontend/src/` реструктурирован по Feature-Sliced Design:
   - `app/App.tsx` + `app/hooks/useAppOverview.ts`
   - `features/{parse,lexicon,assignments,statistics}/ui/`
   - `shared/{ui,hooks,api,utils,styles}/`
2. Path aliases `@app`, `@features`, `@shared` в `vite.config.ts` и `tsconfig.app.json`
3. Старые плоские директории удалены; build: 267 KB JS; тесты: 16/16 passed

### Рефакторинг start.sh (коммит b88b917)
4. `scripts/lib/net.py` — CLI-модуль вместо 5 Python-heredocs (`parse-dsn`, `tcp-probe`, `http-probe`, `llm-probe`)
5. 7 функций `build_*_command()` вместо монолитных printf-блоков
6. 1096 → 854 строки (−22%)

### LLM E2E smoke (коммит b88b917 / f875e0d)
7. Исправлен баг в `scripts/run_llm_stage_check.sh`: не передавались `LLM_SERVICE_EXECUTABLE` и `LLM_SERVICE_MODEL_PATH`
8. Qwen3.5-9B через `ghcr.io/ggml-org/llama.cpp:server` + локальный GGUF
9. Phrasal verbs `look into`, `carry out`, `break down` найдены; stage_progress nlp+llm получены

### Playwright UI smoke (коммит e750e1d)
10. `playwright.config.ts` + `tests/frontend/smoke_ui.spec.ts`: 6 сценариев, headless Firefox
11. **6/6 passed, 19.5s** — Parse (20 строк, `look into`), Lexicon, Assignments, Statistics, Sync, Navigation без JS-ошибок

### Дочистка (коммит 6cbad2d)
12. `.gitignore`: `node_modules/`, `frontend/node_modules/` добавлены
13. `assignments-service` postgres_repository рефакторинг + миграция `0002_units_model.sql`

## Last Updated
2026-03-11
