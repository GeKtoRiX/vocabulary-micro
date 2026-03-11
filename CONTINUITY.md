# CONTINUITY.md

## Current Task
Завершённая зачистка Python shared-layer после cutover: удалены root shim-каталоги, SQL naming-хвосты сведены к минимуму, smoke подтверждён.

## Progress
100%

## Blocked by
Нет блокеров.

## Next Step
При следующей итерации можно отдельно решать, нужен ли rename публичного `async_sync_queue_db_path` в `core`, потому что сейчас он сохранён ради совместимости.

## What Was Done (последний цикл)

1. Удалён `backend/python_services/infrastructure/sqlite/sqlite_lexicon.py` как мёртвый SQLite storage-адаптер, больше не используемый текущим runtime.
2. `backend/python_services/infrastructure/sqlite/text_utils.py` очищен от `sqlite3`-зависимых helper-функций; оставлены только текстовые утилиты, реально нужные NLP-модулям.
3. `backend/python_services/infrastructure/config/settings.py` очищен от неиспользуемого `assignments_db_path`, а `backend/python_services/nlp_service/components.py` переведён с `nlp_service_warmup.sqlite3` на нейтральный probe-файл `nlp_service_warmup.probe`.
4. Исторический пакет `backend/python_services/infrastructure/sqlite/` переименован в `backend/python_services/infrastructure/nlp/`, а затем все Python runtime/test импорты переведены на прямые канонические пути `backend.python_services.core.*` и `backend.python_services.infrastructure.*`.
5. Архитектурные аудиты обновлены так, чтобы ловить запрещённые зависимости и в канонической форме `backend.python_services.infrastructure.*`; root shim-пакеты `core/` и `infrastructure/` удалены.
6. Корневые каталоги `core/` и `infrastructure/` физически удалены после удаления shim-файлов; в репозитории больше не осталось этих namespace в root.
7. Мёртвые `sqlite_busy_timeout_ms` и `sqlite_wal_enabled` вырезаны из `PipelineSettings`, `.sqlite3` defaults заменены на нейтральные store-имена, а docs/user-guide очищены от неактуальных SQL-ссылок вне audit-маркеров.
8. Пройдены проверки: `python3 -m pytest -q tests/backend/unit tests/backend/concurrency/test_shutdown_race.py tests/governance/tools/test_tools_registry.py tests/backend/architecture/test_import_boundaries.py` (`190 passed`), `python3 -m pytest -q tests/backend/unit/core/use_cases/test_parse_and_sync.py -k third_pass` (`7 passed, 15 deselected`), `python3 -m pytest -q tests/backend/unit/infrastructure/config/test_settings.py tests/backend/unit/core/use_cases/test_parse_and_sync.py` (`26 passed`), `python3 -m pytest -q tests/backend/architecture/test_import_boundaries.py tests/governance/tools/test_tools_registry.py` (`9 passed`), `RUN_DOCKER_SMOKE=1 python3 -m pytest -q tests/backend/integration/test_postgres_cutover_smoke.py` (`6 passed`) и `bash scripts/run_docker_smoke.sh` (`6 passed`).

## Last Updated
2026-03-11
