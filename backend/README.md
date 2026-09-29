# Backend планирования выездов

Один FastAPI-сервис: принимает XLSX заявок и инженеров, рассчитывает версии планов
по округам, хранит их в PostgreSQL, отдаёт карточки, события и отчёты. DaData
геокодирует адреса, OSRM/2ГИС дают дорожные матрицы, S3/MinIO хранит исходные
книги и экспорты. Алгоритм — локальный пакет backend, не отдельный сервис.

Действующие маршруты и реальные цепочки действий —
[`../docs/BACKEND.md`](../docs/BACKEND.md); интерактивная схема запущенного API —
<http://localhost:8000/docs>. Обзор всего репозитория —
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

## Запуск

Нужны Docker Compose и локальные настройки:

```bash
cd backend
cp .env.example .env
cp config.toml.example config.toml
# Настройте локальные пароли, DaData и выбранный поставщик матриц.
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

Значения и структура `config.toml` — в `config.toml.example`, секреты Compose —
в `.env.example`. Рабочие `.env` и `config.toml` не добавляйте в Git и не
публикуйте ключи в логах. `make help` перечисляет команды.

## Разработка

```bash
make check                                      # ruff format --check, ruff check, mypy
uv run python -m unittest discover -s tests -v # тесты backend
```

Миграции: `make upgrade`; новые ревизии — `make migrate MSG=...`. HTTP-роутеры,
схемы и доменные сценарии — `src/api/`; БД и транзакции — `src/core/db/`;
алгоритм — `src/core/algorithm/`; внешние API — отдельные клиенты и сервисы в
`src/core/`; сборка зависимостей — `src/core/di/`; конфиг — `src/config/`.
Подробные правила изменения кода — [`agents-docs/`](agents-docs/ARCHITECTURE.md)
и локальный [`AGENTS.md`](AGENTS.md).

Первоначальный импорт требует пару XLSX на округ с окнами **сегодняшнего дня по
Москве**. Файл контрольного распределения не заменяет книгу инженеров. Для
проверки реальной интеграции frontend отключите его автоматический demo-fallback.
