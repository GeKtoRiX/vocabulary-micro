# CONTINUITY.md

## Current Task
Увеличение long-text лимитов до `4096` и live-проверка 10-предложного текста на reasoning-mode + запись в БД.

## Progress
100%

## Blocked by
Нет блокеров.

## Next Step
Следующим шагом при необходимости улучшить post-processing third-pass reasoning: модель на длинном тексте нашла 12 выражений, но всё ещё часто классифицирует phrasal verbs как `idiom`, а automatic `parse+sync` блокируется policy `validation_blocked_high_confidence_trf`.

## What Was Done (последний цикл)

1. Канонические defaults подняты до `4096` в `backend/python_services/infrastructure/config/settings.py`:
   `max_input_tokens=4096` и `third_pass_llm_max_tokens=4096`.
2. Обновлён unit-тест `tests/backend/unit/infrastructure/config/test_settings.py`; проверка прошла: `python3 -m pytest -q tests/backend/unit/infrastructure/config/test_settings.py`.
3. Поднят полный стек через `./start.sh`; live direct `third-pass` на тексте из 10 предложений с `think_mode=true` после увеличения лимита вернул `12` occurrences.
4. Автоматический `POST /internal/v1/nlp/parse` с `sync=true`, `third_pass_enabled=true`, `think_mode=true` всё ещё завершился `third_pass_status=skipped` с policy `validation_blocked_high_confidence_trf`, поэтому automatic DB write не произошёл.
5. Те же live `occurrences`, найденные в reasoning mode, успешно записаны в БД через `ThirdPassOrchestrator.upsert_mwe_records_from_occurrences`: `upserted_count=12`, `failed_count=0`.
6. Post-check SQLite подтвердил запись: `mwe_expressions=12`, `mwe_senses=12` в `backend/python_services/infrastructure/persistence/data/lexicon.sqlite3`.

## Last Updated
2026-03-11
