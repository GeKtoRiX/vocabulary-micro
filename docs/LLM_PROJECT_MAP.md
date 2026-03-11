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
start.sh                                   — thin local launcher entrypoint; sources scripts/start/*.sh
scripts/start/helpers.sh                   — shared env/network/system/postgres/process helpers for launcher
scripts/start/commands.sh                  — service command builders for launcher
scripts/start/runtime.sh                   — launcher orchestration: args, defaults, preflight, bootstrap, readiness
scripts/lib/net.py                         — CLI network utils: parse-dsn, tcp-probe, http-probe, llm-probe
scripts/llama_server_docker.sh             — wrapper: runs ghcr.io/ggml-org/llama.cpp:server via Docker
scripts/run_llm_stage_check.sh             — E2E LLM smoke: starts stack, POST /api/parse, checks SSE stages
scripts/run_docker_smoke.sh                — integration smoke: docker-based stack health checks
playwright.config.ts                       — Playwright UI test config (headless Firefox)
tools.py                                   — compatibility entrypoint for agent tooling
AGENTS.md                                  — policy document for OpenAI Codex (auto-loaded)
CLAUDE.md                                  — policy document for Claude Code / Anthropic agents (auto-loaded)
MEMORY.md                                  — project long-term memory; update on architectural decisions
CONTINUITY.md                              — session recovery point; update after each completed step
agents/                                    — agent tooling + real local skills implementation
frontend/                                  — React 19 + Vite 7 SPA (FSD layout)
backend/services/                          — TypeScript gateway + boundary services
backend/python_services/core/              — canonical Python domain/use case layer
backend/python_services/infrastructure/    — canonical Python adapters/runtime/config layer
backend/python_services/nlp_service/       — Python NLP capability API
backend/python_services/export_service/    — Python export capability API
scripts/                                   — local/dev/bootstrap helpers
docs/                                      — project maps and operator guides
tests/backend/                             — product runtime/unit/integration/service tests
tests/frontend/                            — Playwright UI smoke tests
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
frontend (FSD SPA)
  → backend/services/api-gateway
      → backend/services/lexicon-service
      → backend/services/assignments-service
      → backend/python_services/nlp_service/main.py
      → backend/python_services/export_service/main.py
      [optional] → LLM service (llama.cpp via Docker or vLLM)
```

Python no longer hosts the public `/api/*` runtime. Python is now internal capability runtime only.

## 5) Frontend

Frontend uses **Feature-Sliced Design (FSD)**:

```
frontend/src/
  app/
    App.tsx                    — root component, tab routing
    hooks/useAppOverview.ts    — top-level data orchestration
  features/
    parse/ui/
      ParseTab.tsx             — text input + SSE parse + stage progress popup
      StageProgressPopup.tsx   — NLP/LLM stage indicator
    lexicon/ui/
      LexiconTab.tsx           — sortable/paginated lexicon table
    assignments/ui/
      AssignmentsTab.tsx       — scan SSE + audio + quick-add
    statistics/ui/
      StatisticsTab.tsx        — KPI cards + bar chart
  shared/
    ui/        — SortableTable, Modal, Toast, KpiCard, StatusBadge, SectionMessage, ContextMenu, AudioPlayer
    hooks/     — useSSEJob, useWarmup, useAudio
    api/       — client.ts (fetch wrapper), types.ts
    utils/     — format.ts
    styles/    — globals.css, layout.css, table.css, components.css
  main.tsx     — entry point
```

Path aliases: `@app → ./src/app`, `@features → ./src/features`, `@shared → ./src/shared`

- `frontend/public/` — static assets copied by Vite
- `frontend/dist/` — production build served by gateway in non-dev mode

## 6) Backend Shared Python Layers

### Core Layer

- `backend/python_services/core/domain/` — domain models, repositories, pure services, reason codes
- `backend/python_services/core/use_cases/` — parse/sync orchestration and DTO assembly

### Infrastructure Layer

- `backend/python_services/infrastructure/adapters/` — HTTP and runtime adapters
- `backend/python_services/infrastructure/nlp/` — NLP/search helpers and table models
- `backend/python_services/infrastructure/bootstrap/` — warmup state machine and optional llama.cpp runtime
- `backend/python_services/infrastructure/logging/` — logging, metrics, tracing
- `backend/python_services/infrastructure/persistence/data/` — runtime data directory

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

- storage isolation: assignments stay inside the Postgres owner-service boundary
- scanner path is search-only (`AssignmentScannerService`)
- sync bridge path is explicit (`assignment_sync_use_case`)
- operation order: `sync -> scan`

### 9.3 SSE parse stages

Gateway SSE stream for `/api/parse` emits in order:

1. `progress` — started
2. `stage_progress { stage: "nlp", status: "done"|"error" }` — NLP pipeline result
3. `stage_progress { stage: "llm", status: "done"|"error" }` — third-pass LLM result (only if `third_pass_enabled=true` and `LLM_SERVICE_ENABLED=true`)
4. `result` — full parse payload with `summary`, `rows`, `third_pass_summary`
5. `done`

## 10) Test Commands

```bash
# Python unit
python3 -m pytest -q tests/backend/unit/

# TypeScript unit/integration (vitest)
cd backend/services && npm run test -- --run

# Frontend unit (vitest)
cd frontend && npm run test -- --run

# Playwright UI smoke (headless Firefox)
PLAYWRIGHT_BROWSERS_PATH=~/.cache/playwright ./node_modules/.bin/playwright test

# Architecture boundaries
python3 -m pytest -q tests/backend/architecture/test_import_boundaries.py

# Full Python suite
python3 -m pytest -q tests/

# LLM E2E smoke (requires Qwen3.5-9B GGUF + Docker)
LLM_STAGE_CHECK_REQUIRE_THIRD_PASS_OCCURRENCES=true bash scripts/run_llm_stage_check.sh

# Docker integration smoke
bash scripts/run_docker_smoke.sh
```
