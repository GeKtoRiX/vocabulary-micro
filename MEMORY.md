# MEMORY.md

## Overview
- Репозиторий `vocabulary-main` реализует веб-приложение для управления лексиконом, parse/sync workflow, assignments-аналитики и статистики.
- Проект находится в переходном состоянии: публичный `/api` уже фронтируется через TypeScript gateway, но часть бизнес-логики и capability API остаётся на Python.

## Architecture
- Архитектурная модель: Clean Architecture с жёсткими границами между `core`, `infrastructure`, `api`, `web`, `services`, `python_services`.
- `core` содержит доменные контракты, DTO и use case-слой без внешних зависимостей.
- `infrastructure` содержит адаптеры, SQLite/Postgres runtime-слой, bootstrap, конфигурацию и логирование.
- `services/api-gateway`, `services/lexicon-service`, `services/assignments-service` образуют migration slice для owner-services.
- `python_services/nlp_app.py` и `python_services/export_app.py` выступают внутренними capability API.

## Stack
- Backend Python: FastAPI, Uvicorn, Pydantic, pytest.
- NLP-стек: spaCy, spacy-transformers, lemminflect, nltk.
- Frontend: React + Vite + TypeScript.
- Service layer: Fastify/TypeScript.
- Хранилища: SQLite по умолчанию, Postgres как целевой backend для owner-services.

## Runtime/Services
- Публичная точка входа migration runtime: `services/api-gateway`.
- Lexicon ownership: `services/lexicon-service`.
- Assignments ownership: `services/assignments-service`.
- Legacy execution engine и часть lifecycle остаются на Python.
- В проекте уже существует аудит синхронизации `AGENTS.md` и `docs/agents.md` через `tools.py::audit_docs_sync`.

## Constraints
- Перед mutating-задачами нужно читать `AGENTS.md`, `MEMORY.md`, `CONTINUITY.md`.
- Публичные интерфейсы `core` нельзя менять без отдельной необходимости и явного запроса.
- Реальные секреты не должны попадать в git; разрешены только `.env` и `.env.*.local`.
- Новые ответы агента и новые комментарии в коде ведутся на русском языке.
- Существующие английские docstring и комментарии не переводятся массово.

## Commands
- Архитектурная проверка: `python3 -m pytest -q tests/architecture/test_import_boundaries.py`
- Проверка governance bootstrap: `python3 -m pytest -q tests/unit/tools/test_governance_bootstrap.py`
- Проверка инструментов: `python3 -m pytest -q tests/unit/tools/test_tools_registry.py`

## Decisions
- `2026-03-10` — Создан `CLAUDE.md` в корне репозитория как автозагружаемая точка входа для Claude Code и совместимых агентов.
  Зачем: Claude Code автоматически читает `CLAUDE.md` при старте; без него агенты не знают о `AGENTS.md` и governance-цикле.
- `2026-03-10` — Создан `skills/system_health_guardian.py` с функцией `audit_ui_imports`.
  Зачем: `tools.py` импортирует этот модуль; его отсутствие приводило к постоянному fallback в `audit_import_boundaries`.
- `2026-03-10` — В репозиторий введён bootstrap-контур `AGENTS.md` / `MEMORY.md` / `CONTINUITY.md`.
  Зачем: формализовать правила агентной работы и убрать зависимость continuity-процесса от устных инструкций.
- `2026-03-10` — `docs/agents.md` закреплён как краткая операторская выжимка из `AGENTS.md`.
  Зачем: сделать существующий аудит `tools.py::audit_docs_sync` применимым к реальным файлам проекта.
- `2026-03-10` — Добавлен локальный пакет `skills` с `docs_sync_guardian`.
  Зачем: убрать зависимость `audit_docs_sync` от внешнего окружения и сделать проверку самодостаточной внутри репозитория.
- `2026-03-10` — Добавлен минимальный fallback `skills.semantic_query_engine`.
  Зачем: сохранить импортную совместимость `tools.py` и тестов инструментов без внедрения полного внешнего skill-рантайма.

## Open Risks
- Текущий аудит `docs_sync_guardian` опирается на исторические строковые маркеры и SLA, часть которых нужна только для совместимости.
- Ветка содержит незакоммиченные пользовательские изменения в `services/*` и `tests/services/*`; bootstrap-задачи не должны вмешиваться в них.
- Если governance-документы начнут расходиться с реальной архитектурой migration slice, аудит перестанет быть полезным и потребует пересмотра.
