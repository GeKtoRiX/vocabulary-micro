# Backend Layout

- `services/` — публичный gateway и TS owner-services.
- `python_services/` — внутренние Python capability-сервисы и shared-layer runtime:
  - `core/` — канонический доменный/use case слой Python capability runtime.
  - `infrastructure/` — канонический adapters/runtime/config/logging слой.
  - `nlp_service/` — NLP capability API.
  - `export_service/` — export capability API.

Root `core/` и `infrastructure/` больше не являются местом реализации: это compatibility shim packages для сохранения исторических импортов `core.*` и `infrastructure.*`.
