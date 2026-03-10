# Tests Layout

- `tests/backend/architecture/` — статические boundary-check тесты.
- `tests/backend/concurrency/` — гонки shutdown и lifecycle edge-cases.
- `tests/backend/integration/` — runtime/compose/postgres smoke.
- `tests/backend/services/` — Vitest и Python smoke для gateway и owner-services.
- `tests/backend/unit/` — unit-тесты Python-доменов и infrastructure.
- `tests/governance/tools/` — тесты agent/governance tooling и bootstrap-документов.

Frontend component/unit tests остаются co-located в `frontend/src/**/*.test.tsx`, потому что это стандартный паттерн для Vite/React и он снижает drift между кодом и тестами.
