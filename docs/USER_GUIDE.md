# USER GUIDE: Working With the Agent

## 1. Purpose

This guide explains how to work with the agent safely and effectively in this repository:

- where business logic belongs
- how layer boundaries are enforced
- which checks are required before closing a task

## 2. Architecture in One Line

Data flow:

`Web SPA → api-gateway → JS boundary services / Python capability APIs`

Layer responsibilities:

- `frontend/`: React 19 SPA — FSD layout: `app/`, `features/*/ui/`, `shared/{ui,hooks,api,utils,styles}/`
- `backend/services/`: Fastify gateway and boundary services
- `backend/python_services/core/`: canonical domain contracts, DTOs, use cases, pure services — **never add external deps here**
- `backend/python_services/infrastructure/`: canonical NLP/runtime adapters, config, logging, warmup/bootstrap
- `backend/python_services/`: internal Python capability APIs
- `agents/`: реализация agent tooling и локальных skills
- `tests/backend/`: продуктовые runtime/unit/integration тесты
- `tests/governance/`: проверки bootstrap/governance/tooling-контура

Current migration ownership:

- `lexicon-service` is the active owner for lexicon CRUD/search/categories/statistics and row sync
- `assignments-service` is the active owner for assignments CRUD/scan/update/rescan/quick-add/statistics
- `nlp-service` is the default parse backend for `/api/parse` and `/api/system/warmup`
- `export-service` is the default export backend for `/api/lexicon/export`
- Python runtime is reduced to capability services only: `nlp-service` and `export-service`

## 3. Running the App

```bash
# Full migration slice
bash ./scripts/prepare_docker_runtime.sh  # one-time pull/build step for preloaded local images
./start.sh                     # recommended path: gateway + services on Postgres, local postgres auto-bootstrapped
./start.sh --build             # build frontend, then start gateway + services
./start.sh --dev               # Vite dev server + gateway + services

# Capability APIs
python3 -m backend.python_services.nlp_service.main
python3 -m backend.python_services.export_service.main
```

Env templates:

```bash
cp .env.example .env
cp .env.postgres.example .env.postgres
cp .env.compose.postgres.example .env.compose.postgres
```

`start.sh` automatically loads `.env`, `.env.local`, `.env.postgres`, and `.env.postgres.local`.
The root `start.sh` remains the single local entrypoint, while its implementation is split into
`scripts/start/helpers.sh`, `scripts/start/commands.sh`, and `scripts/start/runtime.sh` for easier maintenance.

Postgres runtime:

```bash
cp .env.postgres.example .env.postgres
./start.sh
```

Recommended default for migration verification: run `./scripts/prepare_docker_runtime.sh` once,
then use plain `./start.sh`. `./start.sh` ensures local docker compose `postgres` is up
when the DSN targets `127.0.0.1` / `localhost`, but no image/dependency downloads are expected
at startup because the prepare step preloads them. Set `START_POSTGRES_VIA_COMPOSE=0` only if you
intentionally use an external Postgres.

The compose/runtime layout now follows the standard split:
- one container for the application services
- one separate Postgres container
- host-persisted database files via `POSTGRES_DATA_DIR` (default `./docker-data/postgres`)
- actual Postgres cluster in `PGDATA` subdirectory inside that mount

Compose Postgres runtime:

```bash
bash ./scripts/prepare_docker_runtime.sh
docker compose up
docker compose --env-file .env.compose.postgres up
```

## 4. Storage and Isolation

- Owner-service persistence runs on Postgres only
- In Postgres mode, owner data is isolated by schema: `LEXICON_POSTGRES_SCHEMA=lexicon` and `ASSIGNMENTS_POSTGRES_SCHEMA=assignments`

Critical invariant:

- `AssignmentGateway` writes only to `assignments.db`
- assignment → lexicon writes are allowed only through `assignment_sync_use_case`

Assignments operation order: `sync → scan`.

## 5. Assignments: Result Semantics

After scan, you get:

- `Known` — matched lexicon entries
- `Missing` — words not in lexicon
- `Diff` — original/completed differences
- `Coverage` — known-token percentage for completed text

Coverage status rules:

- known statuses: `approved`, `pending_review`
- `rejected` is excluded from known coverage by default

## 6. Web UI Quick Orientation

### Parse tab

Text input → parse SSE job → 9-column table. Sync individual rows via context menu.

### Lexicon tab

TanStack Query + 13-column sortable/paginated table. CRUD via modals and context menu.

### Assignments tab

Scan SSE + audio playback + quick-add flow. Bulk rescan and bulk delete supported.

### Statistics tab

KPI cards + canvas bar chart (top-12 coverage) + status/source breakdown + low-coverage list.

## 7. TRF → LLM Gate Policy

Threshold: `ParseSyncSettings.trf_confidence_threshold` (env `TRF_CONFIDENCE_THRESHOLD`, default `0.8`).

Required reason codes:

- `validation_blocked_high_confidence_trf`
- `validation_suspicious_trf_uncertain`
- `validation_second_pass_empty_fallback`
- `validation_no_trf_signal_fallback`
- `validation_trf_not_uncertain`

## 8. Required Checks

### Architecture boundaries

```bash
python3 -m pytest -q tests/backend/architecture/test_import_boundaries.py
```

### Full Python suite

```bash
python3 -m pytest -q tests/
```

### TypeScript service tests

```bash
cd backend/services && npm run test -- --run
```

### Frontend build + unit tests

```bash
cd frontend && npm run build
cd frontend && npm run test -- --run
```

### Playwright UI smoke (headless Firefox)

```bash
PLAYWRIGHT_BROWSERS_PATH=~/.cache/playwright ./node_modules/.bin/playwright test
```

### Postgres cutover smoke

```bash
RUN_DOCKER_SMOKE=1 python3 -m pytest -q tests/backend/integration/test_postgres_cutover_smoke.py
```

### LLM third-pass E2E (requires Qwen3.5-9B GGUF + Docker)

```bash
LLM_STAGE_CHECK_REQUIRE_THIRD_PASS_OCCURRENCES=true bash scripts/run_llm_stage_check.sh
```

## 9. Prompting Pattern That Works Well

Recommended request structure:

1. Goal
2. Constraints (layer/file/SLA/backward-compatibility)
3. Done criteria
4. Mandatory validation commands

Example:

```text
Update assignments quick-add flow.
Keep assignments.db isolation and do not break import boundaries.
Run unit tests + architecture tests.
```
