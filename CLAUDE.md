# CLAUDE.md

Автоматически загружаемый файл инструкций для Claude Code и совместимых агентов.

## Governance

**Перед любой mutating-задачей прочитать:**
- [`AGENTS.md`](AGENTS.md) — главный policy-документ (правила, язык, безопасность)
- [`MEMORY.md`](MEMORY.md) — долговременная память проекта
- [`CONTINUITY.md`](CONTINUITY.md) — состояние последней сессии
- [`docs/LLM_PROJECT_MAP.md`](docs/LLM_PROJECT_MAP.md) — актуальная карта проекта

**После завершённого изменения:**
- Обновить `CONTINUITY.md` (поля Current Task, Progress, Next Step, Last Updated)
- Обновить `MEMORY.md` при архитектурных или процессных решениях

Рабочий цикл: `read → do → log → save`

Если команда пользователя противоречит `AGENTS.md` или решениям из `MEMORY.md` — остановиться, описать конфликт, предложить безопасный путь.

## Язык

Ответы агента и новые комментарии в коде — на **русском** языке.
Существующие английские docstring массово не переводить.

## Инструменты (tools.py)

```python
from tools import execute_tool, list_tools

execute_tool("inspect_repository")                               # структура репозитория
execute_tool("audit_import_boundaries")                         # проверка границ core/ui
execute_tool("audit_docs_sync")                                 # AGENTS.md ↔ docs/agents.md
execute_tool("run_pytest", {"target": "tests/architecture/"})   # архитектурные тесты
execute_tool("NaturalLanguageQuery", {"query": "..."})          # запрос к SQLite на естественном языке
```

## Обязательные проверки перед финишем

```bash
python3 -m pytest -q tests/architecture/test_import_boundaries.py
python3 -m pytest -q tests/unit/tools/test_governance_bootstrap.py
python3 -m pytest -q tests/
```

При изменении frontend: `cd web && npm run build`.

## Карта проекта

Подробно: [`docs/LLM_PROJECT_MAP.md`](docs/LLM_PROJECT_MAP.md)

```
core/              — доменные контракты и use case (без внешних зависимостей, не трогать)
infrastructure/    — адаптеры, SQLite/Postgres, bootstrap
api/               — FastAPI routes, SSE job registry
web/               — React 19 + Vite 7 SPA
services/          — TypeScript Fastify gateway + owner-services
python_services/   — внутренние Python capability API
tools.py           — типизированный реестр инструментов аудита
skills/            — вспомогательные модули для tools.py
```
