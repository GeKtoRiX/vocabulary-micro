# Python Services Layout

- `core/` — канонический Python domain/use case слой для capability runtime.
- `infrastructure/` — канонический Python runtime/adapters/config/logging слой.
- `nlp_service/` — internal NLP capability API.
- `export_service/` — internal export capability API.

Root `core/` и `infrastructure/` оставлены только как compatibility shim packages для исторических импортов `core.*` и `infrastructure.*`.
