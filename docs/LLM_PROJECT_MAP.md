# LLM Project Map

## 1) Purpose

Fast orientation guide for agents working in this repository.

It answers:

- where business logic lives
- how modules interact
- what can be changed safely
- which checks are mandatory before finishing

## 2) Top-Level Layout

```
main_web.py          — thin entry point: uvicorn api.main:app :8765
main_nlp.py          — standalone NLP capability server entry point
main_export.py       — standalone export capability server entry point
start.sh             — bash launcher (--build / --dev / --postgres / --print-config)
tools.py             — typed tool registry for audits and repository inspection
AGENTS.md            — policy document for OpenAI Codex (auto-loaded)
CLAUDE.md            — policy document for Claude Code / Anthropic agents (auto-loaded)
MEMORY.md            — project long-term memory; update on architectural decisions
CONTINUITY.md        — session recovery point; update after each completed step
core/                — framework-agnostic contracts, DTOs, use cases
infrastructure/      — adapters, SQLite engines, config, startup, logging
api/                 — FastAPI routes, schemas, SSE job registry
web/                 — React 19 + Vite 7 SPA (TypeScript + TanStack Query)
services/            — TypeScript Fastify gateway + boundary services
python_services/     — internal Python capability APIs
skills/              — auxiliary modules for tools.py (guardians, semantic engine)
docs/                — project maps and guides for agents and operators
tests/               — architecture, unit, integration, runtime, concurrency, services
```

## 3) Non-Negotiable Boundaries

- `core` must not import `infrastructure` or `api`
- `api` must not import `infrastructure` directly (only via DI in `dependencies.py`)
- SQL and `sqlite3` belong to `infrastructure` only
- `main_web.py`, `main_nlp.py`, `main_export.py` are lifecycle/composition only

Boundary tests:

- `tests/architecture/test_import_boundaries.py`

## 4) Composition Root

Startup chain (web mode):

```
main_web.py
  → uvicorn api.main:app
      → lifespan() in api/main.py
          → infrastructure.bootstrap.web_builder.build_web_components()
              → StartupService (DB init, migrations)
              → InitializationCoordinator (NLP warmup, background thread)
              → repositories + adapters
              → use cases
              → LlamaCppServerManager (optional, if env enabled)
```

Key bootstrap files:

- `infrastructure/bootstrap/web_builder.py` — composition root
- `infrastructure/bootstrap/startup_service.py` — DB init, migrations
- `infrastructure/bootstrap/initialization_coordinator.py` — AI warmup state machine
- `infrastructure/bootstrap/llama_server_runtime.py` — optional llama.cpp process manager

Migration runtime slice:

```
web
  → services/api-gateway
      → services/lexicon-service
      → services/assignments-service
      → main_nlp.py  →  python_services/nlp_app.py   (/internal/v1/nlp/*)
      → main_export.py  →  python_services/export_app.py  (/internal/v1/export/*)
      → main_web.py (legacy execution engine during migration)
```

## 5) Core Layer

### Key contracts and DTOs

- `core/domain/models.py`
- `core/domain/reason_codes.py`
- `core/domain/lexicon_repository.py`
- `core/domain/category_repository.py`
- `core/domain/assignment_repository.py`
- `core/domain/assignment_audio_repository.py`
- `core/domain/assignment_speech_port.py`
- `core/domain/sentence_extractor.py`
- `core/domain/parse_sync_settings.py`
- `core/domain/logging_service.py`
- `core/domain/statistics.py` (via use_cases/statistics.py)

### Key services

- `core/domain/services/mwe_detector.py`
- `core/domain/services/assignment_scanner_service.py`
- `core/domain/services/text_processor.py`
- `core/domain/services/sync_queue.py` — ISyncQueue interface

### Key use cases

- `core/use_cases/parse_and_sync.py`
- `core/use_cases/async_sync_queue_builder.py`
- `core/use_cases/parse_sync_candidate_resolver.py`
- `core/use_cases/third_pass_orchestrator.py`
- `core/use_cases/parse_table_builder.py`
- `core/use_cases/manage_lexicon.py`
- `core/use_cases/manage_categories.py`
- `core/use_cases/manage_assignments.py`
- `core/use_cases/manage_assignment_speech.py`
- `core/use_cases/export_lexicon.py`
- `core/use_cases/statistics.py`

## 6) Infrastructure Layer

### Adapters (`infrastructure/adapters/`)

All domain interface implementations:

- `lexicon_gateway.py` — `ILexiconRepository` + `ICategoryRepository` (SQLite)
- `http_lexicon_gateway.py` — `ILexiconRepository` over HTTP (migration slice)
- `assignment_gateway.py` — `IAssignmentRepository` + `IAssignmentAudioRepository`
- `export_service.py` — `IExportService` (Excel)
- `sync_queue_adapter.py` — `ISyncQueue` (persistent SQLite-backed queue)
- `llm_third_pass.py` — LLM HTTP client (no domain interface)

### SQLite engines (`infrastructure/sqlite/`)

Low-level engines only — no domain interface implementations:

- `sqlite_lexicon.py`, `lexicon_engine.py`
- `management_store.py`, `sqlite_repository.py`
- `index_provider.py`, `mwe_index_provider.py`
- `mwe_second_pass_engine.py`, `mwe_candidate_detector.py`, `mwe_disambiguator.py`
- `mwe_models.py` — MWE data models
- `semantic_matcher.py`, `exact_matcher.py`, `phrase_matcher.py`
- `lemma_inflect_matcher.py`, `wordnet_matcher.py`, `tokenizer.py`
- `assignment_sentence_extractor.py`, `table_models.py`
- `text_utils.py` — shared text normalization helpers

### Logging (`infrastructure/logging/`)

- `app_logger.py` — application-level logger factory
- `file_logger.py` — file sink handler
- `json_logger.py` — structured JSON formatter
- `metrics.py` — lightweight counter/timing helpers
- `tracing.py` — request tracing utilities

### Migrations (`infrastructure/migrations/`)

SQL files applied automatically by `StartupService` on startup.

## 7) API Layer

### Routes (`api/routes/`)

- `system.py` — `GET /api/system/health`, `GET /api/system/warmup`
- `parse.py` — `POST /api/parse`, SSE stream, sync-row
- `lexicon.py` — CRUD `/api/lexicon/entries`, categories, export
- `assignments.py` — scan SSE, CRUD, audio, quick-add, bulk ops
- `statistics.py` — `GET /api/statistics`

### Schemas (`api/schemas/`)

- `lexicon_schemas.py` — Pydantic request/response models for lexicon routes
- `assignment_schemas.py` — Pydantic models for assignments routes
- `parse_schemas.py` — Pydantic models for parse routes

### SSE Jobs pattern

```
POST /api/.../                    → { job_id }
GET  /api/.../jobs/{id}/stream    → SSE: progress / result / done / error
```

`api/jobs.py` — in-process SSE job registry (stores active job state)

### DI (`api/dependencies.py`)

Module-level singletons initialized in lifespan:

- `dep_parse_use_case()` → `ParseAndSyncInteractor`
- `dep_manage_use_case()` → `ManageLexiconInteractor`
- `dep_export_use_case()` → `ExportLexiconInteractor`
- `dep_assignments_use_case()` → `ManageAssignmentsInteractor`
- `dep_statistics_use_case()` → `StatisticsInteractor`
- `dep_coordinator()` → `InitializationCoordinator`
- `get_executor()` → `ThreadPoolExecutor`

## 7.1) Service Layer (Migration)

- `services/api-gateway/src/app.ts` — public `/api` facade, SSE owned here
- `services/api-gateway/src/jobs.ts` — gateway-side SSE job tracking
- `services/lexicon-service/` — lexicon owner: CRUD, category mutations, stats, index, row sync over `sqlite|postgres`
- `services/assignments-service/` — assignments owner: CRUD, scan/update/rescan, quick-add, stats over `sqlite|postgres`
  - `repository.ts` — SQLite storage layer
  - `postgres_repository.ts` — Postgres storage layer
  - `scanner.ts` — assignment scanner logic
  - `storage.ts` — storage interface
- `services/shared/src/` — shared utilities: `config.ts`, `http.ts`, `legacy.ts`, `postgres_migrations.ts`
- `python_services/nlp_app.py` — `/internal/v1/nlp/*`; reads lexicon/MWE state via `lexicon-service`
- `python_services/export_app.py` — `/internal/v1/export/*`, snapshot-based via `lexicon-service`
- `python_services/nlp_components.py` — NLP component wiring shared between nlp_app and legacy path
- `services/contracts/internal-v1.openapi.yaml` — internal contract baseline

## 8) Web Layer (`web/`)

React 19 + Vite 7 SPA, served from `web/dist/` as FastAPI static files.

- `web/src/App.tsx` — tab shell, WarmupBanner, QueryClientProvider
- `web/src/api/client.ts` — fetch wrapper, `openSSEStream()`
- `web/src/api/types.ts` — shared TypeScript API types
- `web/src/hooks/useSSEJob.ts` — POST → SSE → `{status, result}`
- `web/src/hooks/useAppOverview.ts` — aggregated app state hook
- `web/src/hooks/useAudio.ts` — audio playback state hook
- `web/src/hooks/useWarmup.ts` — AI warmup polling hook
- `web/src/tabs/` — ParseTab, LexiconTab, AssignmentsTab, StatisticsTab
- `web/src/components/` — SortableTable, Modal, Toast, KpiCard, ContextMenu, AudioPlayer, SectionMessage, StatusBadge
- `web/src/utils/format.ts` — shared formatting utilities

Build: `cd web && npm run build` → `web/dist/`

## 9) Policy-Critical Flows

### 9.1 Parse and validation gate

`ParseAndSyncInteractor` applies TRF-first policy and conditional third-pass validation with reason codes:

- `validation_blocked_high_confidence_trf`
- `validation_suspicious_trf_uncertain`
- `validation_second_pass_empty_fallback`
- `validation_no_trf_signal_fallback`
- `validation_trf_not_uncertain`

### 9.2 Assignment flow

- storage isolation: assignments in `assignments.db`
- scanner path is search-only (`AssignmentScannerService`)
- sync bridge path is explicit (`assignment_sync_use_case`)
- operation order: `sync -> scan`

### 9.3 Statistics flow

`StatisticsInteractor` combines:

- `ILexiconRepository.get_statistics()`
- `IAssignmentRepository.get_assignment_coverage_stats()`

### 9.4 Assignment speech flow

- `ManageAssignmentSpeechInteractor` orchestrates assignment text → speech
- Reuse-first policy: existing latest audio reused before new synthesis
- Metadata persistence: `assignment_audio` table in `assignments.db`

## 10) Tooling

### Agent entry points (auto-loaded)
- `AGENTS.md` — policy-документ для OpenAI Codex
- `CLAUDE.md` — policy-документ для Claude Code / Anthropic агентов
- `MEMORY.md` — долговременная память проекта; обновлять при архитектурных решениях
- `CONTINUITY.md` — точка восстановления сессии; обновлять после каждого завершённого шага

### Tool registry
- `tools.py` — typed tool registry: `inspect_repository`, `audit_import_boundaries`, `audit_docs_sync`, `run_pytest`, `NaturalLanguageQuery`
- `skills/docs_sync_guardian.py` — аудит синхронизации `AGENTS.md` ↔ `docs/agents.md`
- `skills/system_health_guardian.py` — аудит запрещённых импортов в UI-слое
- `skills/semantic_query_engine.py` — fallback stub для natural-language query
- `tests/unit/tools/test_tools_registry.py` — tests for tools.py
- `tests/unit/tools/test_governance_bootstrap.py` — проверка наличия и структуры governance-файлов

### Scripts
- `cleanup_data.bat` — Windows batch script for DB/cache cleanup
- `start.sh` — bash launcher (`--build`, `--dev` flags)
- `start.sh --postgres` — owner services on Postgres via shared `OWNER_SERVICES_*` env defaults
- `start.sh --print-config` — inspect resolved runtime config after `.env`/profile loading
- `.env.example`, `.env.postgres.example`, `.env.compose.postgres.example` — local runtime templates for SQLite default and Postgres-first flows
- `.env.compose.sqlite.example` — SQLite compose fallback template
- `docker-compose.yml` — Postgres-first compose runtime
- `requirements.compose.txt` — additional requirements for compose deployments

## 11) Test Coverage Map

```
tests/
├── architecture/          — import boundary checks (AST-based, fast)
├── concurrency/           — shutdown race condition tests
├── integration/           — Postgres cutover smoke (requires Docker)
├── services/              — TypeScript service tests (vitest)
│   ├── test_assignments_scanner.test.ts
│   ├── test_assignments_service.test.ts
│   ├── test_gateway_export_headers.test.ts
│   ├── test_gateway_failure_modes.test.ts
│   ├── test_gateway_jobs.test.ts
│   ├── test_gateway_legacy_contract.test.ts
│   ├── test_gateway_statistics.test.ts
│   ├── test_legacy_sse.test.ts
│   ├── test_lexicon_bootstrap.test.ts
│   ├── test_lexicon_service.test.ts
│   ├── test_service_smoke.test.ts
│   ├── test_shared_config.test.ts
│   ├── test_shared_http.test.ts
│   └── test_python_internal_services.py
└── unit/
    ├── core/domain/       — domain models and services
    ├── core/use_cases/    — use case interactors
    ├── infrastructure/    — adapters, SQLite engines, bootstrap, config, logging
    ├── runtime/           — startup and warmup integration
    └── tools/             — tools.py registry and governance bootstrap
```

## 12) Mandatory Quality Gates

### Architecture boundaries

```bash
python3 -m pytest -q tests/architecture/test_import_boundaries.py
```

### Governance bootstrap

```bash
python3 -m pytest -q tests/unit/tools/test_governance_bootstrap.py
```

### Full Python test suite

```bash
python3 -m pytest -q tests/
```

### TypeScript service tests

```bash
cd services && npm test
```

### Postgres cutover smoke

```bash
RUN_DOCKER_SMOKE=1 python3 -m pytest -q tests/integration/test_postgres_cutover_smoke.py
```

### Compose Postgres smoke

```bash
bash .github/scripts/compose_postgres_smoke.sh
```

### Build frontend

```bash
cd web && npm run build
```

## 13) Agent Finish Checklist

1. Validate boundary compliance (`tests/architecture/`).
2. Run targeted tests for touched modules.
3. Run full Python test suite.
4. If TypeScript services changed: `cd services && npm test`.
5. If frontend changed: `cd web && npm run build` and verify no TS errors.
6. Update `CONTINUITY.md` with current task state.
7. Update `MEMORY.md` if architectural or process decisions were made.
8. Report skipped checks and blockers explicitly.
