# CONTINUITY.md

## Current Task
Удаление legacy SQLite backend для owner-services, smoke-подтверждение и публикация изменений.

## Progress
100%

## Blocked by
Нет блокеров.

## Next Step
При необходимости разобрать оставшиеся внутренние Python sqlite-модули по статусу `используется сейчас / legacy / можно удалить позже`.

## What Was Done (последний цикл)

1. `backend/services/shared/src/config.ts` переведён на Postgres-only owner-service config без `LEXICON_DB_PATH`, `ASSIGNMENTS_DB_PATH` и sqlite/bootstrap toggles.
2. `backend/services/lexicon-service/src/app.ts` и `backend/services/assignments-service/src/app.ts` больше не умеют откатываться в SQLite и всегда поднимают Postgres repositories.
3. `scripts/start/{runtime,commands}.sh`, `docker-compose.yml`, `.env*` templates и `README.md`/`docs/USER_GUIDE.md` очищены от sqlite fallback path; `./start.sh` теперь Postgres-first без отдельного обязательного `--postgres`.
4. Из репозитория удалены legacy runtime артефакты `.env.compose.sqlite.example`, `tests/backend/services/test_lexicon_bootstrap.test.ts`, а также tracked `assignments.db-shm` / `assignments.db-wal`.
5. Service-тесты переписаны на mock Postgres repositories вместо temp sqlite-файлов; прогнаны `cd backend/services && npm run test -- --run` и `bash -n scripts/start/runtime.sh && bash -n scripts/start/commands.sh`.
6. Живой Postgres smoke подтверждён командами `RUN_DOCKER_SMOKE=1 python3 -m pytest -q tests/backend/integration/test_postgres_cutover_smoke.py` и `bash scripts/run_docker_smoke.sh`; обе проверки прошли (`6 passed`).

## Last Updated
2026-03-11
