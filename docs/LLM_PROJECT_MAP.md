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
start.sh                                   — local launcher for frontend + backend runtime
tools.py                                   — compatibility entrypoint for agent tooling
AGENTS.md                                  — policy document for OpenAI Codex (auto-loaded)
CLAUDE.md                                  — policy document for Claude Code / Anthropic agents (auto-loaded)
MEMORY.md                                  — project long-term memory; update on architectural decisions
CONTINUITY.md                              — session recovery point; update after each completed step
agents/                                    — agent tooling + real local skills implementation
frontend/                                  — React 19 + Vite 7 SPA
backend/services/                          — TypeScript gateway + boundary services
backend/python_services/core/              — canonical Python domain/use case layer
backend/python_services/infrastructure/    — canonical Python adapters/runtime/config layer
backend/python_services/nlp_service/       — Python NLP capability API
backend/python_services/export_service/    — Python export capability API
core/                                      — compatibility shim for historical `core.*` imports
infrastructure/                            — compatibility shim for historical `infrastructure.*` imports
scripts/                                   — local/dev/bootstrap helpers
docs/                                      — project maps and operator guides
tests/backend/                             — product runtime/unit/integration/service tests
tests/governance/                          — governance + agent-tooling tests
skills/                                    — compatibility wrappers for historical `skills.*` imports
```

## 3) Non-Negotiable Boundaries

- `core` must not import `infrastructure` or any HTTP/runtime layer
- SQL and `sqlite3` belong to `infrastructure` only
- `backend/python_services/*/main.py` are lifecycle/composition only
- public `/api/*` enters only through `backend/services/api-gateway`

Boundary tests:

- `tests/backend/architecture/test_import_boundaries.py`

## 4) Runtime Slice

Supported runtime:

```
frontend
  → backend/services/api-gateway
      → backend/services/lexicon-service
      → backend/services/assignments-service
      → backend/python_services/nlp_service/main.py
      → backend/python_services/export_service/main.py
```

Python no longer hosts the public `/api/*` runtime. Python is now internal capability runtime only.

## 5) Frontend

- `frontend/src/` — tabs, hooks, components, API client, app shell
- `frontend/public/` — static assets copied by Vite
- `frontend/dist/` — production build served by gateway in non-dev mode

## 6) Backend Shared Python Layers

### Core Layer

- `backend/python_services/core/domain/` — domain models, repositories, pure services, reason codes
- `backend/python_services/core/use_cases/` — parse/sync orchestration and DTO assembly

### Infrastructure Layer

- `backend/python_services/infrastructure/adapters/` — HTTP and runtime adapters
- `backend/python_services/infrastructure/sqlite/` — SQLite-backed NLP/search helpers and table models
- `backend/python_services/infrastructure/bootstrap/` — warmup state machine and optional llama.cpp runtime
- `backend/python_services/infrastructure/logging/` — logging, metrics, tracing
- `backend/python_services/infrastructure/persistence/data/` — default SQLite files

Root `core` and `infrastructure` remain only as compatibility shim packages so historical imports continue to work while the canonical implementation lives under `backend/python_services/`.

## 7) Backend Service Layer

- `backend/services/api-gateway/` — public `/api` facade, SSE orchestration, static frontend serving
- `backend/services/lexicon-service/` — lexicon owner: CRUD, categories, statistics, export snapshot, row sync
- `backend/services/assignments-service/` — assignments owner: CRUD, scan/update/rescan, quick-add, statistics
- `backend/services/shared/src/` — shared TS utilities: config, HTTP, contracts, legacy bridge helpers
- `backend/services/contracts/internal-v1.openapi.yaml` — source of truth for internal `/internal/v1/*` contracts

## 8) Python Capability APIs

- `backend/python_services/nlp_service/app.py` — `/internal/v1/nlp/*`, `/internal/v1/system/*`
- `backend/python_services/nlp_service/components.py` — runtime wiring for `ParseAndSyncInteractor`, warmup, and lexicon HTTP gateway
- `backend/python_services/nlp_service/main.py` — standalone runner for uvicorn
- `backend/python_services/export_service/app.py` — `/internal/v1/export/*`, `/internal/v1/system/health`
- `backend/python_services/export_service/main.py` — standalone runner for uvicorn

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
