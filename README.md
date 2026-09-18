# __PROJECT_TITLE__

Готовый шаблон backend-приложения на FastAPI: DI на dishka, SQLAlchemy + Alembic,
структурные логи, метрики Prometheus и полный docker-compose стек с мониторингом
(Prometheus, Loki, Promtail, cAdvisor, Grafana).

## Стек

- **FastAPI** + **uvicorn**
- **dishka** — dependency injection
- **SQLAlchemy** (async) + **asyncpg** + **Alembic** — БД и миграции
- **pydantic-settings** — конфиг из `config.toml` / `.env` / переменных окружения
- **prometheus-client** — метрики приложения (`/metrics`)
- **Prometheus + Grafana + Loki + Promtail + cAdvisor** — мониторинг и логи в docker-compose
- **ruff** + **mypy** — линт и типизация

## Быстрый старт

```bash
cp .env.example .env
cp config.toml.example config.toml
make up
```

Приложение поднимется на `http://localhost:8000`, Grafana — на `http://localhost:3000`
(логин/пароль из `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` в `.env`).

Локально без docker (нужен поднятый Postgres):

```bash
make upgrade   # применить миграции
make run       # запустить приложение
```

## Команды Makefile

```
make help
```

- `up` / `down` / `build` / `logs` / `ps` — управление docker-compose стеком
- `upgrade` / `downgrade REV=<rev>` / `migrate MSG=<msg>` — миграции Alembic
- `format` / `lint` / `lint-fix` / `typecheck` / `check` — качество кода
- `run` — запуск приложения локально

## Структура

```
src/
  api/            корневой роутер и исключения API
  config/         конфигурация (pydantic-settings)
  core/
    db/           модели, DTO, репозитории, unit of work
    di/           провайдеры dishka
    metrics.py    Prometheus-мидлварь
    middleware.py логирующая мидлварь (request id, статус, длительность)
    logging.py    настройка структурных логов
  main.py         сборка FastAPI-приложения
deploy/           конфиги prometheus/promtail/grafana для docker-compose
alembic/          миграции
```

## Конфигурация

Настройки читаются из `config.toml` (см. `config.toml.example`) и переопределяются
переменными окружения с разделителем `__`, например `DATABASE__POSTGRES_HOST`.
Секреты для docker-compose (пароли Postgres и Grafana) — в `.env` (см. `.env.example`).

## Использование как шаблона

Это GitHub template repository — можно создать новый репозиторий кнопкой
**Use this template** вместо `git clone`. При первом пуше в новом репозитории
автоматически отработает workflow, который подставит имя проекта вместо плейсхолдеров
(`__PROJECT_TITLE__`, `__PROJECT_PACKAGE__`, `__PROJECT_SLUG__`) и удалит сам себя.
