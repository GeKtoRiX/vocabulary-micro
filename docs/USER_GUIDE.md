# USER GUIDE: Working With the Agent

## 1. Purpose

This guide explains how to work with the agent safely and effectively in this repository:

- where business logic belongs
- how layer boundaries are enforced
- which checks are required before closing a task

## 2. Architecture in One Line

Data flow:

`Web SPA → FastAPI (api/) → Core Use Cases → Infrastructure Adapters → SQLite`

Migration slice:

`Web SPA → api-gateway → JS boundary services / Python capability APIs / legacy backend`

Layer responsibilities:

- `core/`: domain contracts, DTOs, use cases, pure services — **never add external deps here**
- `infrastructure/`: SQLite engines, adapters, config, logging, startup, migrations
- `api/`: FastAPI routes, schemas, SSE job registry, dependency injection
- `web/`: React 19 SPA — tabs, hooks, components
- `services/`: Fastify gateway and boundary services
- `python_services/`: internal Python capability APIs

Current migration ownership:

- `lexicon-service` is the active owner for lexicon CRUD/search/categories/statistics and row sync
- `assignments-service` is the active owner for assignments CRUD/scan/update/rescan/quick-add/statistics
- `nlp-service` is the default parse backend for `/api/parse` and `/api/system/warmup`
- `export-service` is the default export backend for `/api/lexicon/export`
- legacy FastAPI runtime is kept as compatibility fallback and parity reference, not as the primary path

Composition root: `infrastructure/bootstrap/web_builder.py`

## 3. Running the App

```bash
# Full migration slice
./start.sh --postgres          # recommended production-like path: gateway + services on Postgres
./start.sh                     # local SQLite fallback path
./start.sh --build             # build frontend, then start gateway + services
./start.sh --dev               # Vite dev server + gateway + services

# Legacy backend only
LEGACY_BACKEND_PORT=8766 python3 main_web.py

# Capability APIs
python3 main_nlp.py
python3 main_export.py
```

Env templates:

```bash
cp .env.example .env
cp .env.postgres.example .env.postgres
cp .env.compose.postgres.example .env.compose.postgres
cp .env.compose.sqlite.example .env.compose.sqlite
```

`start.sh` automatically loads `.env`, `.env.local`, and `.env.postgres` when `--postgres` is used.

Postgres cutover runtime:

```bash
cp .env.postgres.example .env.postgres
./start.sh --postgres
```

Recommended default for migration verification: prefer the Postgres-first runtime and use plain `./start.sh`
only when you explicitly want the SQLite dev fallback. `./start.sh` without `--postgres`
does not switch owner services to Postgres by itself.

Compose Postgres runtime:

```bash
docker compose up
docker compose --env-file .env.compose.postgres up
```

Explicit Compose SQLite fallback:

```bash
docker compose --env-file .env.compose.sqlite up
```

## 4. Assignment Speech Wiring

- Speech use case: `ManageAssignmentSpeechInteractor`
- Generation policy:
  - reuse latest existing audio when file exists (`assignment_speech_reused_existing_audio`)
  - otherwise synthesize and persist metadata (`assignment_speech_generated`)

## 5. Storage and Isolation

- Lexicon DB: `infrastructure/runtime/data/lexicon.sqlite3`
- Assignments DB: `infrastructure/runtime/data/assignments.db` (includes `assignment_audio` metadata)
- Both owner services support `sqlite|postgres` storage backends via `LEXICON_STORAGE_BACKEND` and `ASSIGNMENTS_STORAGE_BACKEND`
- In Postgres mode, owner data is isolated by schema: `LEXICON_POSTGRES_SCHEMA=lexicon` and `ASSIGNMENTS_POSTGRES_SCHEMA=assignments`

Critical invariant:

- `AssignmentGateway` writes only to `assignments.db`
- assignment → lexicon writes are allowed only through `assignment_sync_use_case`

Assignments operation order: `sync → scan`.

## 6. Assignments: Result Semantics

After scan, you get:

- `Known` — matched lexicon entries
- `Missing` — words not in lexicon
- `Diff` — original/completed differences
- `Coverage` — known-token percentage for completed text

Coverage status rules:

- known statuses: `approved`, `pending_review`
- `rejected` is excluded from known coverage by default

## 7. Web UI Quick Orientation

### Parse tab

Text input → parse SSE job → 9-column table. Sync individual rows via context menu.

### Lexicon tab

TanStack Query + 13-column sortable/paginated table. CRUD via modals and context menu.

### Assignments tab

Scan SSE + audio playback + quick-add flow. Bulk rescan and bulk delete supported.

### Statistics tab

KPI cards + canvas bar chart (top-12 coverage) + status/source breakdown + low-coverage list.

## 8. TRF → LLM Gate Policy

Threshold: `ParseSyncSettings.trf_confidence_threshold` (env `TRF_CONFIDENCE_THRESHOLD`, default `0.8`).

Required reason codes:

- `validation_blocked_high_confidence_trf`
- `validation_suspicious_trf_uncertain`
- `validation_second_pass_empty_fallback`
- `validation_no_trf_signal_fallback`
- `validation_trf_not_uncertain`

## 9. Required Checks

### Architecture boundaries

```bash
python3 -m pytest -q tests/architecture/test_import_boundaries.py
```

### Full suite

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

### Frontend build

```bash
cd web && npm run build
```

## 10. Prompting Pattern That Works Well

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
