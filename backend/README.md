# Backend планирования выездов

Один FastAPI-сервис: принимает XLSX заявок и инженеров, рассчитывает версии планов
по округам, хранит их в PostgreSQL, отдаёт карточки, события и отчёты. DaData
геокодирует адреса, OSRM/2ГИС дают дорожные матрицы, S3/MinIO хранит исходные
книги и экспорты. Алгоритм — локальный пакет backend, не отдельный сервис.

Интерактивная схема действующего API — <http://localhost:8000/docs>. Первичный
сценарий: загрузить XLSX-пару через `/api/planning/initial`, проверить созданный
pending-план через `/api/plans/{id}`, затем утвердить или отклонить. Для
перепланирования есть `/api/planning/replan`, для внештатных событий —
`/api/planning/events`; карточки, выгрузки и дневной отчёт — в доменных маршрутах.
Все маршруты и формы ответа доступны в `/openapi.json`.

## Запуск

Нужны Docker Compose и локальные настройки:

```bash
cd backend
cp -n .env.example .env
# Настройте локальные пароли и ключ DaData; провайдер матриц — в .env.
make up
```

API: <http://localhost:8000>; `/metrics` — Prometheus. Compose также поднимает
PostgreSQL, MinIO и мониторинг (Grafana: <http://localhost:3000>). По умолчанию
Compose публикует PostgreSQL на `127.0.0.1:5432`; при конфликте используйте
локальный override. `make ps` показывает состояние, `make logs` — логи,
`make down` останавливает стек.

Для запуска Python локально нужна среда `uv` и работающие PostgreSQL/S3-сервисы:

```bash
uv sync
make upgrade
make run
```

Для локального `make run` можно создать `config.toml` из `config.toml.example`;
Docker берёт секреты и ключи из `.env` (образ не включает рабочий TOML).
Рабочие `.env` и `config.toml` не добавляйте в Git и не
публикуйте ключи в логах. `make help` перечисляет команды.

## Разработка

```bash
make check                                      # ruff format --check, ruff check, mypy
make test                                       # unit-тесты без Docker/сети
make test-matrix                                # каталог тестовых сценариев
```

`make test-integration` и `make test-e2e` создают одноразовый PostgreSQL через
Docker; подробности — в [`tests/README.md`](tests/README.md). Миграции:
`make upgrade`; новые ревизии — `make migrate MSG=...`. HTTP-роутеры,
схемы и доменные сценарии — `src/api/`; БД и транзакции — `src/core/db/`;
алгоритм — `src/core/algorithm/`; внешние API — отдельные клиенты и сервисы в
`src/core/`; сборка зависимостей — `src/core/di/`; конфиг — `src/config/`.
Подробные правила изменения кода — [`agents-docs/`](agents-docs/ARCHITECTURE.md)
и локальный [`AGENTS.md`](AGENTS.md).

Первоначальный импорт требует пару XLSX на округ с окнами **сегодняшнего дня по
Москве**, по умолчанию использует `balanced` + `lns`; CSV не принимает.
Файл контрольного распределения не заменяет книгу инженеров. Для
проверки реальной интеграции frontend отключите его автоматический demo-fallback.
