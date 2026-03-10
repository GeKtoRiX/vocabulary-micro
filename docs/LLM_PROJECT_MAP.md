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
start.sh             — bash launcher (--build / --dev flags)
core/                — framework-agnostic contracts, DTOs, use cases
infrastructure/      — adapters, SQLite engines, config, startup, logging, migrations
api/                 — FastAPI routes, schemas, SSE job registry
web/                 — React 19 + Vite 7 SPA (TypeScript + TanStack Query)
services/            — TypeScript Fastify gateway + boundary services
python_services/     — internal Python capability APIs
tools.py             — typed tool registry for audits and repository inspection
tests/               — architecture, unit, runtime, concurrency checks
```

## 3) Non-Negotiable Boundaries

- `core` must not import `infrastructure` or `api`
- `api` must not import `infrastructure` directly (only via DI in `dependencies.py`)
- SQL and `sqlite3` belong to `infrastructure` only
- `main_web.py` is lifecycle/composition only

Boundary tests:

- `tests/architecture/test_import_boundaries.py`

## 4) Composition Root

Startup chain:

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
      → python_services/nlp_app.py
      → python_services/export_app.py
      → main_web.py (legacy execution engine during migration)
```

## 5) Core Layer

### Key contracts and DTOs

- `core/domain/models.py`
- `core/domain/reason_codes.py`
- `core/domain/lexicon_repository.py`
- `core/domain/assignment_repository.py`
- `core/domain/assignment_audio_repository.py`
- `core/domain/assignment_speech_port.py`
- `core/domain/statistics.py`

### Key services

- `core/domain/services/mwe_detector.py`
- `core/domain/services/assignment_scanner_service.py`
- `core/domain/services/text_processor.py`

### Key use cases

- `core/use_cases/parse_and_sync.py`
- `core/use_cases/async_sync_queue_builder.py`
- `core/use_cases/parse_sync_candidate_resolver.py`
- `core/use_cases/third_pass_orchestrator.py`
- `core/use_cases/parse_table_builder.py`
- `core/use_cases/manage_lexicon.py`
- `core/use_cases/manage_assignments.py`
- `core/use_cases/manage_assignment_speech.py`
- `core/use_cases/statistics.py`

## 6) Infrastructure Layer

### Adapters (`infrastructure/adapters/`)

All domain interface implementations:

- `lexicon_gateway.py` — `ILexiconRepository` + `ICategoryRepository`
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
- `semantic_matcher.py`, `exact_matcher.py`, `phrase_matcher.py`
- `lemma_inflect_matcher.py`, `wordnet_matcher.py`, `tokenizer.py`
- `assignment_sentence_extractor.py`, `table_models.py`

### Migrations (`infrastructure/migrations/`)

SQL files applied automatically by `StartupService` on startup.

## 7) API Layer

### Routes (`api/routes/`)

- `system.py` — `GET /api/system/health`, `GET /api/system/warmup`
- `parse.py` — `POST /api/parse`, SSE stream, sync-row
- `lexicon.py` — CRUD `/api/lexicon/entries`, categories, export
- `assignments.py` — scan SSE, CRUD, audio, quick-add, bulk ops
- `statistics.py` — `GET /api/statistics`

### SSE Jobs pattern

```
POST /api/.../                    → { job_id }
GET  /api/.../jobs/{id}/stream    → SSE: progress / result / done / error
```

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

- `services/api-gateway/` — public `/api` facade, SSE owned here
- `services/lexicon-service/` — lexicon owner service for CRUD, category mutations, stats, index, and row sync over `sqlite|postgres`
- `services/assignments-service/` — assignments owner service for CRUD, scan/update/rescan, quick-add, and stats over `sqlite|postgres`
- `python_services/nlp_app.py` — default parse capability backend for `/internal/v1/nlp/*`; reads lexicon/MWE state via `lexicon-service` internal APIs
- `python_services/export_app.py` — `/internal/v1/export/*`, now snapshot-based via `lexicon-service`
- `services/contracts/internal-v1.openapi.yaml` — internal contract baseline

## 8) Web Layer (`web/`)

React 19 + Vite 7 SPA, served from `web/dist/` as FastAPI static files.

- `web/src/App.tsx` — tab shell, WarmupBanner, QueryClientProvider
- `web/src/api/client.ts` — fetch wrapper, `openSSEStream()`
- `web/src/hooks/useSSEJob.ts` — POST → SSE → `{status, result}`
- `web/src/tabs/` — ParseTab, LexiconTab, AssignmentsTab, StatisticsTab
- `web/src/components/` — SortableTable, Modal, Toast, KpiCard, ContextMenu, AudioPlayer

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

- `tools.py` — typed tool registry: `inspect_repository`, `audit_import_boundaries`, `run_pytest`, `NaturalLanguageQuery`
- `tests/unit/tools/test_tools_registry.py` — tests for tools.py
- `cleanup_data.bat` — Windows batch script for DB/cache cleanup
- `start.sh` — bash launcher (`--build`, `--dev` flags)
- `start.sh --postgres` — owner services on Postgres via shared `OWNER_SERVICES_*` env defaults
- `start.sh --print-config` — inspect resolved runtime config after `.env`/profile loading
- `.env.example`, `.env.postgres.example`, `.env.compose.postgres.example` — local runtime templates for SQLite default and Postgres-first flows
- `docker-compose.yml` — Postgres-first compose runtime; SQLite compose fallback lives in `.env.compose.sqlite.example`

## 11) Mandatory Quality Gates

### Architecture boundaries

```bash
python3 -m pytest -q tests/architecture/test_import_boundaries.py
```

### Full test suite

```bash
python3 -m pytest -q tests/
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

## 12) Agent Finish Checklist

1. Validate boundary compliance (`tests/architecture/`).
2. Run targeted tests for touched modules.
3. Run full test suite.
4. If frontend changed: `npm run build` and verify no TS errors.
5. Report skipped checks and blockers explicitly.
