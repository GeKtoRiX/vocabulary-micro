# MEMORY.md

## Overview
- Репозиторий `vocabulary-main` реализует веб-приложение для управления лексиконом, parse/sync workflow, assignments-аналитики и статистики.
- Проект находится в переходном состоянии: публичный `/api` уже фронтируется через TypeScript gateway, но часть бизнес-логики и capability API остаётся на Python.

## Architecture
- Архитектурная модель: Clean Architecture с жёсткими границами между `backend/python_services/core`, `backend/python_services/infrastructure`, `frontend`, `backend/services`, `backend/python_services/*_service`.
- Канонический Python domain/use case слой живёт в `backend/python_services/core`.
- Канонический Python adapters/runtime/config/logging слой живёт в `backend/python_services/infrastructure`.
- Root `core` и `infrastructure` сохранены как compatibility shim packages для исторических импортов.
- `backend/services/api-gateway`, `backend/services/lexicon-service`, `backend/services/assignments-service` образуют migration slice для owner-services.
- `backend/python_services/nlp_service/app.py` и `backend/python_services/export_service/app.py` выступают внутренними capability API.

## Stack
- Backend Python: FastAPI, Uvicorn, Pydantic, pytest.
- NLP-стек: spaCy, spacy-transformers, lemminflect, nltk.
- Frontend: React + Vite + TypeScript.
- Service layer: Fastify/TypeScript.
- Хранилища: owner-services работают на Postgres; SQLite остаётся только во внутренних Python runtime/adapters, где это явно требуется инфраструктуре.

## Runtime/Services
- Публичная точка входа migration runtime: `backend/services/api-gateway`.
- Lexicon ownership: `backend/services/lexicon-service`.
- Assignments ownership: `backend/services/assignments-service`.
- Legacy execution engine и часть lifecycle остаются на Python.
- В проекте уже существует аудит синхронизации `AGENTS.md` и `docs/agents.md` через `tools.py::audit_docs_sync`.

## Constraints
- Перед mutating-задачами нужно читать `AGENTS.md`, `MEMORY.md`, `CONTINUITY.md`.
- Публичные интерфейсы `core` нельзя менять без отдельной необходимости и явного запроса.
- Реальные секреты не должны попадать в git; разрешены только `.env` и `.env.*.local`.
- Новые ответы агента и новые комментарии в коде ведутся на русском языке.
- Существующие английские docstring и комментарии не переводятся массово.

## Commands
- Архитектурная проверка: `python3 -m pytest -q tests/backend/architecture/test_import_boundaries.py`
- Проверка governance bootstrap: `python3 -m pytest -q tests/governance/tools/test_governance_bootstrap.py`
- Проверка инструментов: `python3 -m pytest -q tests/governance/tools/test_tools_registry.py`

## Decisions
- `2026-03-11` — Legacy SQLite backend вырезан из owner-services runtime: `loadConfig`, `start.sh`, `docker-compose.yml`, env templates и TypeScript service app factory теперь поддерживают только Postgres для `lexicon-service` и `assignments-service`.
  Зачем: держать два параллельных owner-storage path (`sqlite` и `postgres`) стало дороже, чем польза от dev-fallback; Postgres уже является целевым и основным runtime, а сохранение legacy toggle усложняло запуск, тесты и документацию.
- `2026-03-11` — Лимиты long-text third-pass подняты до `4096`: Python pipeline теперь принимает до `4096` входных токенов, а third-pass LLM generation budget тоже увеличен до `4096`.
  Зачем: live проверка на тексте из 10 предложений с idiom/phrasal verb показала, что прежние `2048`/`256` лимиты были узким местом — tokenizer мог резать длинный вход, а в `think_mode=true` Qwen/llama.cpp успевал выдать только начало reasoning и не доходил до parseable payload.
- `2026-03-11` — На локальном `llama.cpp`/ROCm path для RX 7600 XT live third-pass проверка оказалась чувствительна к ROCm env: c `HSA_OVERRIDE_GFX_VERSION=11.0.0` и `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` сервер поднимается и отвечает, а без них прямой wrapper-запуск падал до обслуживания запросов.
  Зачем: это зафиксированное инфраструктурное условие для воспроизводимого локального smoke `thinking on/off`; без этих env ложный вывод был бы таким, будто сломан `think_mode`, хотя фактически падал сам runtime.
- `2026-03-11` — Third-pass LLM prompt для MWE extraction ужесточён: system/user prompt теперь явно разводят `phrasal_verb` и `idiom`, требуют dictionary-form canonicalization, запрещают догадки и предписывают пустой `occurrences` при сомнении.
  Зачем: локальный runtime на C1-примерах путал фразовые глаголы с идиомами и иногда возвращал слишком свободные кандидаты; более жёсткий taxonomy + no-guess contract снижает ложные срабатывания и лучше направляет Qwen/llama.cpp на точный JSON-ответ.
- `2026-03-11` — Third-pass LLM adapter переведён на streaming OpenAI-compatible chat path с `chat_template_kwargs.enable_thinking`, а `scripts/llama_server_docker.sh` по умолчанию использует ROCm-образ `ghcr.io/ggml-org/llama.cpp:server-rocm` и пробрасывает AMD GPU/HSA env.
  Зачем: на локальном llama.cpp runtime потоковая обработка chunk-by-chunk лучше согласуется с реальным поведением сервера, упрощает работу с `reasoning_content` и снижает риск таймаутов ожидания полного ответа; отдельный ROCm default-path закрепляет рабочий AMD local-first сценарий без ручной перенастройки wrapper-скрипта.
- `2026-03-11` — `start.sh` разделён на thin entrypoint + shell-модули `scripts/start/{helpers,commands,runtime}.sh`, при этом внешний интерфейс запуска (`./start.sh ...`) сохранён без изменений.
  Зачем: монолитный launcher стал трудно поддерживать и безопасно править; разнесение по зонам ответственности упрощает локальные изменения, review и точечную проверку без изменения bootstrap-поведения.
- `2026-03-11` — Для local `Qwen3.5-9B-GGUF` через `llama.cpp` third-pass extraction использует fallback-парсинг `reasoning_content`, если OpenAI-compatible chat response возвращает пустой `message.content`.
  Зачем: на реальном `llama.cpp` runtime Qwen3.5 стабильно отдавал кандидатов phrasal verb/idiom внутри `reasoning_content`, а не в финальном `content`, из-за чего third-pass формально завершался `status=ok`, но возвращал пустые `occurrences`; fallback позволяет сохранить живой LLM-path без смены runtime и подтверждён реальным e2e smoke на `look into` / `spill the beans` / `carry out`.
- `2026-03-11` — Managed third-pass LLM service в `start.sh` переведён с жёсткой привязки к `vLLM` на runtime-переключаемую схему `llama_cpp | vllm`, где локальный default-path теперь `llama.cpp + GGUF`, а `vLLM` оставлен как опциональный backend.
  Зачем: реальная runtime-проверка на пользовательском AMD/ROCm железе показала, что исходный `vLLM + fp8` сценарий упирается сначала в VRAM pressure, а затем в аппаратно неподдерживаемый FP8 kernel path; при этом пользователь уже подтвердил рабочий опыт с GGUF/LM Studio, так что local-first `llama.cpp` path даёт наиболее реалистичный способ сохранить отдельный LLM-микросервис без переписывания gateway/NLP/UI-контуров.
- `2026-03-11` — Third-pass LLM runtime выделен в отдельный managed vLLM ROCm микросервис, который поднимается из `start.sh`, а `api-gateway` оркестрирует parse как `NLP -> optional LLM third-pass` с публичными SSE `stage_progress` событиями для UI.
  Зачем: Qwen3.5-9B требует отдельного OpenAI-совместимого inference runtime, который нельзя надёжно обслуживать через текущий `llama.cpp` path; разделение lifecycle упрощает bootstrap, а stage-level SSE позволяет фронтенду показывать долгий LLM-шаг без ложного впечатления, что parse завис.
- `2026-03-11` — `Assignments` owner-flow переведён с scan-oriented модели `title + original/completed + coverage` на nested persistence/model `Unit -> Subunits`, при этом публичный namespace `/assignments` сохранён, а legacy scan endpoints оставлены только как отдельный compatibility path вне нового UI/statistics.
  Зачем: пользовательский сценарий перестал быть “сканировать отдельное задание” и стал “собирать юниты с подюнитами”; сохранение старого storage/UI/contracts держало бы ложную предметную модель, ломало бы статистику и вынуждало бы фронтенд жить на неактуальных `coverage/diff` полях.
- `2026-03-10` — `start.sh` переведён на managed lifecycle: перед запуском он проверяет обязательные команды, занятость портов, локальные Node runtime-артефакты и readiness всех HTTP-сервисов, а при `Ctrl+C` завершает каждый сервис по process group и останавливает локально поднятый compose `postgres`.
  Зачем: сделать локальный bootstrap предсказуемым одной командой, исключить “полустартовавший” стек и гарантировать освобождение портов без ручного `pkill`/`docker stop`.
- `2026-03-10` — Postgres compose/runtime persistence переведён с Docker named volume на явный host bind mount `POSTGRES_DATA_DIR` (по умолчанию `./docker-data/postgres`), а сам кластер перенесён в `PGDATA` подпапку внутри mount.
  Зачем: сделать хранение БД прозрачным для локальной разработки, чтобы данные физически лежали в папке проекта на диске хоста и переживали пересборку/обновление контейнеров без скрытого Docker-managed volume, не ломаясь из-за служебных файлов вроде `.gitignore` в корне bind mount.
- `2026-03-10` — Compose/runtime bootstrap переведён на prebuilt local images: добавлены `docker/Dockerfile.python-runtime`, `docker/Dockerfile.node-runtime` и одноразовый prepare-step `scripts/prepare_docker_runtime.sh`, после которого startup больше не делает `pip install`, `npm install` или image pull.
  Зачем: отделить тяжёлые сетевые скачивания и сборку от startup-path, чтобы `docker compose up` и `start.sh --postgres` использовали только уже подготовленные локальные образы и поднимались без сетевой активности.
- `2026-03-10` — `start.sh --postgres` переведён в self-contained bootstrap: при локальном DSN (`127.0.0.1` / `localhost`) он сам поднимает `docker compose` сервис `postgres` и ждёт `healthy` перед стартом application-слоя, но если Postgres уже доступен по заданному DSN, compose-autostart пропускается.
  Зачем: убрать ручной двухшаговый запуск “сначала база, потом start.sh”, сделать production-like Postgres path воспроизводимым одной командой и одновременно не ломать сценарии с уже поднятым внешним/тестовым Postgres на локальном хосте.
- `2026-03-10` — Канонические shared-layer каталоги Python перенесены в `backend/python_services/{core,infrastructure}`, а root `core/` и `infrastructure/` оставлены как compatibility shim packages.
  Зачем: закончить структурное разведение backend-кода, собрать весь Python runtime под `backend/python_services/` и при этом не ломать существующие импорты `core.*` / `infrastructure.*`, тесты и runtime contracts.
- `2026-03-10` — Agent/tooling implementation сгруппирован в `agents/`, а тестовый контур разложен на `tests/backend/` и `tests/governance/`; root `tools.py` и `skills/` оставлены как compatibility entrypoints.
  Зачем: отделить продуктовые тесты от governance-проверок, собрать агентный implementation-контур в одном месте и одновременно не ломать существующие импорты, автозагрузку и локальные workflow.
- `2026-03-10` — Топология репозитория нормализована вокруг явных границ `frontend/` и `backend/`: SPA перенесён в `frontend/`, TypeScript owner-services в `backend/services/`, а Python capability-runtime сгруппирован в `backend/python_services/{nlp_service,export_service}` с отдельными `main.py`.
  Зачем: убрать смешение frontend/backend в корне, сделать Python микросервисы читаемыми как единый runtime-контур и сократить навигационную путаницу без массового namespace-рефакторинга `core`/`infrastructure`.
- `2026-03-10` — Удалён legacy Python web runtime (`main_web.py`, `api/`, SQLite web adapters/use cases), а Python-контур оставлен только для capability-сервисов `nlp-service` и `export-service`.
  Зачем: migration slice уже переключён на TypeScript gateway + owner-services; сохранение параллельного FastAPI-монолита держало мёртвые Python entrypoints, legacy bootstrap и лишние SQLite-адаптеры, не нужные для актуального runtime.
- `2026-03-10` — Compose-рантайм для TypeScript owner-services переведён на общий bootstrap `scripts/ensure_services_node_modules.sh` с файловой блокировкой перед `npm install`.
  Зачем: убрать недетерминированные падения `lexicon-service`/`assignments-service`/`api-gateway` при параллельном старте в `docker compose`, где сервисы делят один bind-mounted `/app/services/node_modules`.
- `2026-03-10` — Internal/public parse serialization нормализована вокруг фактического SPA-контракта: API больше не сдвигает колонки `ParseAndSyncResultDTO.table`, а `known`/`confidence` фиксированы как строковые поля в OpenAPI и runtime validators.
  Зачем: устранить runtime drift между legacy parse table и gateway/NLP contract layer, из-за которого `parse` падал на internal validation и фронт получал некорректные token rows.
- `2026-03-10` — Workspace dev entrypoints TS-сервисов вынесены в `src/dev.ts`, а `loadConfig()` научен подниматься до корня репозитория.
  Зачем: `npm --workspace ... run dev` запускал сервисы из package cwd и ломал поиск `web/dist`, SQLite путей и других project-root-зависимых файлов.
- `2026-03-10` — Owner-service Postgres runtime закреплён за отдельными schema `lexicon` и `assignments`, а таблица учёта миграций `service_postgres_migrations` оставлена в `public`.
  Зачем: изолировать данные владельцев без shared tables и сохранить единый служебный bookkeeping-слой для migration runner и smoke-проверок.
- `2026-03-10` — `backend/services/contracts/internal-v1.openapi.yaml` расширен до source of truth для внутренних `/internal/v1/*` DTO, а TS migration slice получил общий contract/validator слой в `backend/services/shared/src/contracts.ts`.
  Зачем: зафиксировать межсервисные payload shape до дальнейшего cutover и сделать contract drift обнаружимым тестами и runtime-валидацией.
- `2026-03-10` — `api-gateway` перестал добавлять `request_id` в публичный `/api/system/health` и SSE frames.
  Зачем: сохранить strict public parity с legacy FastAPI, оставив correlation id только во внутренних заголовках и трассировке.
- `2026-03-10` — Создан `CLAUDE.md` в корне репозитория как автозагружаемая точка входа для Claude Code и совместимых агентов.
  Зачем: Claude Code автоматически читает `CLAUDE.md` при старте; без него агенты не знают о `AGENTS.md` и governance-цикле.
- `2026-03-10` — Создан `agents/skills/system_health_guardian.py` с compatibility-обёрткой в root `skills/system_health_guardian.py`.
  Зачем: `tools.py` импортирует этот модуль; его отсутствие приводило к постоянному fallback в `audit_import_boundaries`.
- `2026-03-10` — В репозиторий введён bootstrap-контур `AGENTS.md` / `MEMORY.md` / `CONTINUITY.md`.
  Зачем: формализовать правила агентной работы и убрать зависимость continuity-процесса от устных инструкций.
- `2026-03-10` — `docs/agents.md` закреплён как краткая операторская выжимка из `AGENTS.md`.
  Зачем: сделать существующий аудит `tools.py::audit_docs_sync` применимым к реальным файлам проекта.
- `2026-03-10` — Добавлен локальный пакет `agents/skills` с compatibility-слоем в root `skills/` для `docs_sync_guardian`.
  Зачем: убрать зависимость `audit_docs_sync` от внешнего окружения и сделать проверку самодостаточной внутри репозитория.
- `2026-03-10` — Добавлен минимальный fallback `agents/skills/semantic_query_engine.py` с compatibility-обёрткой в root `skills/semantic_query_engine.py`.
  Зачем: сохранить импортную совместимость `tools.py` и тестов инструментов без внедрения полного внешнего skill-рантайма.

## Open Risks
- Текущий аудит `docs_sync_guardian` опирается на исторические строковые маркеры и SLA, часть которых нужна только для совместимости.
- Ветка содержит незакоммиченные пользовательские изменения в `backend/services/*` и `tests/backend/services/*`; bootstrap-задачи не должны вмешиваться в них.
- Если governance-документы начнут расходиться с реальной архитектурой migration slice, аудит перестанет быть полезным и потребует пересмотра.
