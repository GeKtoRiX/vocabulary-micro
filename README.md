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
- `lexicon-service` already owns lexicon CRUD, categories, statistics slice, internal index, and `sync-row` over Postgres
- `assignments-service` now owns assignments CRUD, scan/update/rescan, quick-add suggestions, and assignments statistics over Postgres
- `nlp-service` is the default parse backend for `/api/parse*` and `/api/system/warmup`
- `nlp-service` now loads lexicon and MWE state over `lexicon-service` internal APIs instead of reading SQLite directly
- `export-service` builds Excel exports from `lexicon-service` API snapshots instead of reading SQLite directly
- owner services run on Postgres only and share `OWNER_SERVICES_POSTGRES_URL` defaults
- routing is controlled with feature flags such as `GATEWAY_PARSE_BACKEND`, `GATEWAY_LEXICON_BACKEND`, `GATEWAY_ASSIGNMENTS_BACKEND`

## Installation

```bash
pip install -r requirements.txt
cd frontend && npm install
cd ../backend/services && npm install
bash ./scripts/prepare_docker_runtime.sh
```

Optional local env templates:

```bash
cp .env.example .env
cp .env.postgres.example .env.postgres
cp .env.compose.postgres.example .env.compose.postgres
```

`start.sh` automatically loads `.env`, `.env.local`, `.env.postgres`, and `.env.postgres.local` if present.

## Run

```bash
./start.sh              # gateway + internal services + built SPA
./start.sh --build      # build frontend, then start all services
./start.sh --dev        # Vite dev server + all backend services
./start.sh --postgres   # compatibility alias for the same Postgres-first runtime
```

Or directly:

```bash
python3 -m backend.python_services.nlp_service.main     # internal NLP capability API
python3 -m backend.python_services.export_service.main  # internal export capability API
cd backend/services && npm --workspace @vocabulary/api-gateway run dev

OWNER_SERVICES_POSTGRES_URL=postgresql://postgres:postgres@127.0.0.1:5432/vocabulary \
./start.sh
```

Or with an env file:

```bash
cp .env.postgres.example .env.postgres
bash ./scripts/prepare_docker_runtime.sh
./start.sh
```

Docker Compose:

```bash
bash ./scripts/prepare_docker_runtime.sh
docker compose up    # Postgres-first default runtime, no install/download on startup

docker compose --env-file .env.compose.postgres up
```

`./scripts/prepare_docker_runtime.sh` pulls `postgres:16` and builds local runtime images
`vocabulary-python-runtime:local` and `vocabulary-node-runtime:local`. After that, `./start.sh`
and `docker compose up` use only already prepared local images and do not install/download dependencies on boot.

`./start.sh` bootstraps the local `postgres` compose service automatically when
`OWNER_SERVICES_POSTGRES_URL` points to `127.0.0.1` or `localhost`. Set `START_POSTGRES_VIA_COMPOSE=0`
if you want to target an already running external Postgres instead.

Compose runs Postgres as a separate container and persists its data on the host filesystem via
`POSTGRES_DATA_DIR` (default: `./docker-data/postgres`). You can rebuild or replace application
containers without losing database files. The actual Postgres cluster is stored in the `PGDATA`
subdirectory inside that mount so the bind mount root can safely contain helper files like `.gitignore`.

The compose Postgres template uses `requirements.compose.txt` for Python services so smoke/CI can start without downloading the full `spacy-transformers` / `torch` stack.

Or with an env file:

```bash
bash ./scripts/prepare_docker_runtime.sh
docker compose --env-file .env.compose.postgres up
```

## Architecture

Clean Architecture with strict dependency boundaries:

```
frontend/                React 19 + Vite 7 SPA — Feature-Sliced Design
  src/app/               root component + top-level hooks
  src/features/          parse/, lexicon/, assignments/, statistics/
  src/shared/            ui/, hooks/, api/, utils/, styles/
backend/services/        TypeScript gateway and boundary microservices
backend/python_services/ internal Python capability APIs + shared Python runtime
scripts/lib/             shared shell helpers (net.py — TCP/HTTP/LLM probes)
agents/                  agent tooling and local skills implementation
tests/backend/           backend/runtime/unit/integration test suites
tests/frontend/          Playwright UI smoke tests (headless Firefox)
tests/governance/        governance and agent-tooling checks
```

Frontend path aliases: `@app`, `@features`, `@shared` (configured in `vite.config.ts` and `tsconfig.app.json`).

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
| `OWNER_SERVICES_POSTGRES_URL` | Shared Postgres DSN for owner services |
| `LEXICON_POSTGRES_URL` | Postgres DSN for `lexicon-service` |
| `ASSIGNMENTS_POSTGRES_URL` | Postgres DSN for `assignments-service` |
| `ASSIGNMENT_COMPLETED_THRESHOLD_PERCENT` | Coverage threshold |
| `ASSIGNMENT_DIFF_VIEWER_ENABLED` | Enable diff viewer |
| `ENABLE_SECOND_PASS_WSD` | Enable word-sense disambiguation |
| `ENABLE_THIRD_PASS_LLM` | Enable LLM third pass |
| `THIRD_PASS_LLM_BASE_URL` | LLM server URL |
| `THIRD_PASS_LLM_MODEL` | LLM model alias |
| `THIRD_PASS_LLM_TIMEOUT_MS` | Timeout for NLP -> LLM third-pass request |
| `GATEWAY_JOB_TTL_MS` | TTL for long-running SSE jobs in gateway |
| `BERT_MODEL_NAME` | SBERT model name |
| `BERT_LOCAL_FILES_ONLY` | Use local model files only |

### llama-server autostart (optional)

| Variable | Description |
|---|---|
| `LLAMA_SERVER_AUTOSTART_ENABLED` | Set to `1` to enable |
| `LLAMA_SERVER_EXECUTABLE` | Path to `llama-server` binary or command in `PATH` |
| `LLAMA_SERVER_MODEL_PATH` | Path to `.gguf` model |
| `LLAMA_SERVER_N_GPU_LAYERS` | GPU layers (`-1` = full offload) |

### Managed LLM service in `start.sh`

`start.sh` can now manage the third-pass LLM service directly.

Recommended local path:

- `LLM_SERVICE_ENABLED=true`
- `LLM_SERVICE_RUNTIME=llama_cpp`
- `LLM_SERVICE_EXECUTABLE=llama-server`
- `LLM_SERVICE_MODEL_PATH=/absolute/path/to/model.gguf`
- `THIRD_PASS_LLM_TIMEOUT_MS=300000`
- `GATEWAY_JOB_TTL_MS=420000`

Optional ROCm `vLLM` path remains available through `LLM_SERVICE_RUNTIME=vllm`, but it depends on hardware/backend support for the selected quantization path.

Live smoke scripts:

- `bash scripts/run_llm_stage_check.sh` — starts stack + POST /api/parse + validates stage_progress for nlp and llm
- `bash scripts/llama_server_docker.sh` — wrapper for `ghcr.io/ggml-org/llama.cpp:server` with local GGUF mount

## Tests

```bash
# Python unit + integration
python3 -m pytest -q tests/

# TypeScript service tests (vitest)
cd backend/services && npm run test -- --run

# Frontend unit tests (vitest)
cd frontend && npm run test -- --run

# Playwright UI smoke (headless Firefox, 6 scenarios)
PLAYWRIGHT_BROWSERS_PATH=~/.cache/playwright ./node_modules/.bin/playwright test

# Architecture boundary checks
python3 -m pytest -q tests/backend/architecture/

# LLM third-pass E2E (requires Qwen3.5-9B GGUF + Docker)
LLM_STAGE_CHECK_REQUIRE_THIRD_PASS_OCCURRENCES=true bash scripts/run_llm_stage_check.sh

# Docker integration smoke
bash scripts/run_docker_smoke.sh
```

## Data Storage

- Owner services persist to Postgres only
- Default schemas: `lexicon` and `assignments`
# vocabulary-micro
