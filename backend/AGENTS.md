# AGENTS.md

**Этот файл грузится харнессом автоматически в любую сессию, работающую в
`backend/`, включая субагентов — весь остальной список ниже НЕТ, его нужно
открывать явно, и не по умолчанию.** Список — для сессии, планирующей
нетривиальную задачу, не для каждого делегированного вызова.

**Если ты — субагент, получивший точечную задачу** (найти файл/символ,
поправить один файл, ответить на конкретный вопрос по промпту) — **не читай
файлы из списка ниже**, если это прямо не запрошено в твоём промпте или не
понадобилось по ходу самой задачи.

**Прочитай перед началом работы** (только при планировании/реализации
нетривиальной задачи):

- [agents-docs/ARCHITECTURE.md](./agents-docs/ARCHITECTURE.md) — слои:
  router → service → UoW/repositories → models, DI (dishka), как добавить
  новую сущность.
- [agents-docs/CODE_STYLE.md](./agents-docs/CODE_STYLE.md) — импорты,
  типизация, наименование, docstring, ошибки/исключения API, логирование.
- [agents-docs/PROJECT_CONTEXT.md](./agents-docs/PROJECT_CONTEXT.md) —
  техническая карта (модели/эндпоинты/DI-провайдеры), сейчас пуста — шаблон
  ещё не оброс доменной логикой.
- [../docs/team_discussions/SUMMARY.md](../docs/team_discussions/SUMMARY.md)
  — согласованные командой решения: сущности, эндпоинты, алгоритм, экраны.
  Приоритетнее внутренних догадок там, где расходится с ТЗ.
- [../docs/source_files/TECHNICAL_CONSTRAINTS.md](../docs/source_files/TECHNICAL_CONSTRAINTS.md)
  — исходное ТЗ в сжатом виде: поля заявки/инженера, справочники, три
  обязательных ограничения алгоритма, формат ввода/вывода.
- [../docs/GITFLOW.md](../docs/GITFLOW.md) — ветки (`main`/`dev`/рабочие),
  Pull Request, формат коммитов (Conventional Commits на русском).

---

## Структура backend

```
src/
├── api/                 — корневой роутер (APIRouter, prefix="/api")
│                          доменные роутеры: src/api/<domain>/{router,schemas}.py
├── config/               — pydantic-settings конфиг (config.py, TOML)
├── core/
│   ├── db/
│   │   ├── models/        — SQLAlchemy ORM-модели
│   │   ├── dto/            — датаклассы для передачи данных между слоями
│   │   ├── repositories/    — один репозиторий на модель, без бизнес-логики
│   │   └── uow.py            — UnitOfWork, агрегирует репозитории
│   ├── di/                 — dishka providers
│   ├── logging.py           — структурные JSON-логи
│   ├── metrics.py           — Prometheus-метрики (/metrics)
│   └── middleware.py        — request-логирование, X-Request-Id
└── main.py                  — сборка FastAPI-приложения, единственная точка входа
alembic/                     — миграции БД
agents-docs/                 — документация для агента (архитектура/кодстайл/карта)
.claude/skills/               — commit, add-migration
```

Слоя `src/core/services/` в шаблоне пока нет — заводится, как только
появляется первая бизнес-логика сложнее CRUD (распределение заявок,
перепланирование, сравнение планов) — см. `agents-docs/ARCHITECTURE.md`.

---

## Команды

```bash
make up         # docker compose up --build -d (backend + Postgres + мониторинг)
make down
make logs
make run         # запустить приложение локально без Docker
make migrate MSG="..."   # создать автомиграцию (см. скилл add-migration)
make upgrade              # применить все миграции
make check                 # ruff format --check + ruff check + mypy — перед каждым коммитом
make lint-fix
```

Пакетный менеджер: `uv`. Тестового раннера пока нет в `pyproject.toml`
(`pytest` не подключён) — добавление тестовой инфраструктуры обсуждается с
пользователем отдельно, не тихо заодно с фичей.
