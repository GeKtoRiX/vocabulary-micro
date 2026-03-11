# Agents Layout

- `tooling/` — реализации агентных утилит и реестров.
- `skills/` — локальные skill-модули, которые использует tooling и аудит.

В корне намеренно остаются только entrypoint-файлы совместимости:

- [AGENTS.md](/home/cbandy/vocabulary-main/AGENTS.md)
- [CLAUDE.md](/home/cbandy/vocabulary-main/CLAUDE.md)
- [MEMORY.md](/home/cbandy/vocabulary-main/MEMORY.md)
- [CONTINUITY.md](/home/cbandy/vocabulary-main/CONTINUITY.md)
- [tools.py](/home/cbandy/vocabulary-main/tools.py)
- `skills/` как compatibility-layer для исторических импортов `skills.*`

Это позволяет держать агентный implementation-контур собранным в одном месте, не ломая автозагрузку и существующие тесты.

Launcher runtime при этом тоже оставлен совместимым на корневом entrypoint:

- [start.sh](/home/cbandy/vocabulary-main/start.sh) — единая команда запуска
- `scripts/start/` — модульная реализация launcher (`helpers.sh`, `commands.sh`, `runtime.sh`)
