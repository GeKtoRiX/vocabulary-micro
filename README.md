# Vocabulary

Web application for lexicon management, parse/sync workflows, assignments analysis, and statistics.

## Migration Slice

The repository now contains a runnable migration slice for the backend split:

- `backend/services/api-gateway/` - public `TypeScript + Fastify` gateway for `/api/*`
- `backend/services/lexicon-service/` - JS lexicon boundary service
- `backend/services/assignments-service/` - JS assignments boundary service
- `backend/python_services/nlp_service/app.py` - internal Python NLP capability API
- `backend/python_services/export_service/app.py` - internal Python export capability API
- `backend/services/contracts/internal-v1.openapi.yaml` - source-of-truth internal service contract

Current implementation is transitional by design:

- SPA still uses the same `/api` contract
- gateway is the public entrypoint
- `lexicon-service` already owns lexicon CRUD, categories, statistics slice, internal index, and `sync-row` over SQLite
- `assignments-service` now owns assignments CRUD, scan/update/rescan, quick-add suggestions, and assignments statistics over SQLite
- `nlp-service` is the default parse backend for `/api/parse*` and `/api/system/warmup`
- `nlp-service` now loads lexicon and MWE state over `lexicon-service` internal APIs instead of reading SQLite directly
- `export-service` builds Excel exports from `lexicon-service` API snapshots instead of reading SQLite directly
- `lexicon-service` now supports `LEXICON_STORAGE_BACKEND=sqlite|postgres`; SQLite remains default
- both owner services also support shared runtime toggles via `OWNER_SERVICES_STORAGE_BACKEND`, `OWNER_SERVICES_POSTGRES_URL`, and `OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE`
- routing is controlled with feature flags such as `GATEWAY_PARSE_BACKEND`, `GATEWAY_LEXICON_BACKEND`, `GATEWAY_ASSIGNMENTS_BACKEND`

## Installation

```bash
pip install -r requirements.txt
cd frontend && npm install
cd ../backend/services && npm install
```

Optional local env templates:

```bash
cp .env.example .env
cp .env.postgres.example .env.postgres
cp .env.compose.postgres.example .env.compose.postgres
cp .env.compose.sqlite.example .env.compose.sqlite
```

`start.sh` automatically loads `.env`, `.env.local`, and, with `--postgres`, `.env.postgres` / `.env.postgres.local` if present.

## Run

```bash
./start.sh              # gateway + internal services + built SPA
./start.sh --build      # build frontend, then start all services
./start.sh --dev        # Vite dev server + all backend services
./start.sh --postgres   # owner services on Postgres using OWNER_SERVICES_* defaults
```

Or directly:

```bash
python3 -m backend.python_services.nlp_service.main     # internal NLP capability API
python3 -m backend.python_services.export_service.main  # internal export capability API
cd backend/services && npm --workspace @vocabulary/api-gateway run dev

OWNER_SERVICES_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/vocabulary \
./start.sh --postgres
```

Or with an env file:

```bash
cp .env.postgres.example .env.postgres
./start.sh --postgres
```

Docker Compose:

```bash
docker compose up    # Postgres-first default runtime

docker compose --env-file .env.compose.postgres up
```

The compose Postgres template uses `requirements.compose.txt` for Python services so smoke/CI can start without downloading the full `spacy-transformers` / `torch` stack.

Or with an env file:

```bash
docker compose --env-file .env.compose.postgres up
docker compose --env-file .env.compose.sqlite up
```

## Architecture

Clean Architecture with strict dependency boundaries:

```
frontend/                React + Vite + TypeScript SPA
backend/services/        TypeScript gateway and boundary microservices
backend/python_services/ internal Python capability APIs + shared Python runtime
core/                    compatibility shim package for historical `core.*` imports
infrastructure/          compatibility shim package for historical `infrastructure.*` imports
agents/                   agent tooling and local skills implementation
tests/backend/            backend/runtime/unit/integration test suites
tests/governance/         governance and agent-tooling checks
```

Agent support files are intentionally split into two layers:

- `agents/` contains the real implementations for local skills and tooling.
- root `tools.py` and `skills/` remain as compatibility entrypoints for existing imports and agent workflows.

### SSE Jobs pattern

Long-running operations use Server-Sent Events:

```
POST /api/.../job    → { job_id }
GET  /api/jobs/{id}  → stream: progress / result / done / error
```

## Configuration

Environment variables:

| Variable | Description |
|---|---|
| `ASSIGNMENTS_DB_PATH` | Path to assignments database |
| `OWNER_SERVICES_STORAGE_BACKEND` | Shared default backend for owner services: `sqlite` or `postgres` |
| `OWNER_SERVICES_POSTGRES_URL` | Shared Postgres DSN for owner services |
| `OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE` | Shared one-time seed of empty Postgres from current SQLite snapshots |
| `LEXICON_STORAGE_BACKEND` | `sqlite` or `postgres` for `lexicon-service` |
| `LEXICON_POSTGRES_URL` | Postgres DSN for `lexicon-service` |
| `LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE` | One-time seed of empty Postgres from current SQLite snapshot |
| `ASSIGNMENTS_STORAGE_BACKEND` | `sqlite` or `postgres` for `assignments-service` |
| `ASSIGNMENTS_POSTGRES_URL` | Postgres DSN for `assignments-service` |
| `ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE` | One-time seed of empty Postgres from current SQLite snapshot |
| `ASSIGNMENT_COMPLETED_THRESHOLD_PERCENT` | Coverage threshold |
| `ASSIGNMENT_DIFF_VIEWER_ENABLED` | Enable diff viewer |
| `ENABLE_SECOND_PASS_WSD` | Enable word-sense disambiguation |
| `ENABLE_THIRD_PASS_LLM` | Enable LLM third pass |
| `THIRD_PASS_LLM_BASE_URL` | LLM server URL |
| `THIRD_PASS_LLM_MODEL` | LLM model alias |
| `BERT_MODEL_NAME` | SBERT model name |
| `BERT_LOCAL_FILES_ONLY` | Use local model files only |

### llama-server autostart (optional)

| Variable | Description |
|---|---|
| `LLAMA_SERVER_AUTOSTART_ENABLED` | Set to `1` to enable |
| `LLAMA_SERVER_EXECUTABLE` | Path to `llama-server` binary |
| `LLAMA_SERVER_MODEL_PATH` | Path to `.gguf` model |
| `LLAMA_SERVER_N_GPU_LAYERS` | GPU layers (`-1` = full offload) |

## Tests

```bash
python3 -m pytest -q tests/
```

Architecture boundary checks:

```bash
python3 -m pytest -q tests/backend/architecture/
```

Governance / agent-tooling checks:

```bash
python3 -m pytest -q tests/governance/tools/
```

Compose smoke in CI:

```bash
bash .github/scripts/compose_postgres_smoke.sh
```

## Data Storage

- Lexicon DB: `backend/python_services/infrastructure/persistence/data/lexicon.sqlite3`
- Assignments DB: `backend/python_services/infrastructure/persistence/data/assignments.db`
# vocabulary-micro
