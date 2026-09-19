# Протокол проверки 19.09.2026

Commit: `3b8985c77dc41a9fffbb025f1b80fa630dbf178e`. Каталог запуска команд: `project/backend`.
Исходники, тесты и uv.lock во время проверки не менялись. Все записи тестового приложения выполнялись во временные БД, внешние geocoding/routing API не вызывались.

## Окружение

- Python 3.12.14 из bundled runtime.
- Отдельная среда: `/private/tmp/beeline-audit-20260919-venv`.
- Установка точно по существующему lock: `uv sync --frozen --no-install-project`.
- `PYTHONPATH=src`, `PYTHONDONTWRITEBYTECODE=1`; кэши и basetemp перенесены в `/private/tmp`.
- Сначала выполнена offline-попытка в пустом отдельном cache: пакет mypy отсутствовал. После разрешённой сетевой установки frozen-зависимостей проверки прошли. Это ограничение установки, не ошибка проекта.

```sh
UV_PROJECT_ENVIRONMENT=/private/tmp/beeline-audit-20260919-venv \
UV_CACHE_DIR=/private/tmp/beeline-audit-20260919-cache \
uv sync --frozen --no-install-project \
  --python /Users/daniilfrolov/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3

PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  /private/tmp/beeline-audit-20260919-venv/bin/python -m pytest \
  -p no:cacheprovider --basetemp=/private/tmp/beeline-audit-20260919-pytest

/private/tmp/beeline-audit-20260919-venv/bin/ruff check . --no-cache

PYTHONDONTWRITEBYTECODE=1 /private/tmp/beeline-audit-20260919-venv/bin/python \
  -m mypy src --cache-dir=/private/tmp/beeline-audit-20260919-mypy
```

| Проверка | Результат |
|---|---|
| Полный pytest | **42 passed, 2 warnings**, 1.65 s |
| Ruff | All checks passed |
| mypy | Success: no issues found in 23 source files |
| SQLite migration | upgrade head + alembic check: успешно, no new upgrade operations |
| PostgreSQL 16 migration | upgrade → check → downgrade base → upgrade → check: успешно |
| PostgreSQL HTTP | import, duplicate import, plan, approve, event, audit, diff, stale approval, approve new version, XLSX/PDF, dashboard, readiness: успешно |

Два предупреждения штатной suite — deprecation Starlette TestClient/httpx и anyio BlockingPortal. Это не падения тестов.

Для PostgreSQL создан только новый контейнер `beeline-audit-20260919` из локального `postgres:16-alpine`, без томов, с динамическим портом localhost. Использован полученный `127.0.0.1:55026`; APP_ENV=development, demo providers. Выполнена функция существующего теста `test_import_plan_approve_replan_diff_and_reports` через TestClient против мигрированной PostgreSQL. После проверки `docker stop` удалил контейнер благодаря `--rm`. Рабочие контейнеры/базы не менялись. Downgrade выполнялся исключительно на этой новой audit-БД.

## Негативные эксперименты

Полный исполняемый сценарий сохранён в [REPRODUCE.md](REPRODUCE.md), результаты — в [results.json](results.json). Это диагностические наблюдения, **не зелёные regression-тесты правильности**: в них намеренно зафиксировано неправильное поведение текущего commit.

| Эксперимент | Фактический результат | Связь с отчётом |
|---|---|---|
| COMPLETED в snapshot | Назначен, validator принимает | A01 |
| HTTP SENT → EN_ROUTE → IN_PROGRESS → COMPLETED → plans/run | Выполненный request снова в assignments | A01 |
| as_of=13:00, availability=08:00 | start=08:10, validator принимает | A02 |
| Две urgent-заявки: подключение и авария, помещается только одна | Назначено подключение, авария unassigned | A03 |
| Walking travel=6000, driving=600 | Пешеходу назначены 600 секунд, validator принимает | A06 |
| Нет требуемого skill | Назначений нет, missing_skill | Соответствие №10 |
| Engineer исключён из roster, его lock сохранён | KeyError | A05 |
| HTTP unavailable при EN_ROUTE в approved plan | HTTP 500 | A05 |
| Некорректный UUID в payload urgent_request | HTTP 500 | A14 |
| window_start без timezone, window_end с +03:00 | HTTP 500 | A14 |
| POST /requests с fail-once planner, затем тот же idempotency key | 422 → 200 duplicate=true/replanning=null; вызов planner только один | A13 |
| Отмена effective_at=17:00, затем snapshot as_of=12:00 | CANCELLED при пустом списке events | A11 |
| IN_PROGRESS(actual_start) → отмена через /events | actual_start последнего fact = null | A12 |
| Неизвестный routing_provider='dgsi' | demo_haversine | A17 |
| Изменённая версия той же XLSX | /requests: 4; новый план: 2 | A16 |
| Второй день того же региона | 0 назначений, no_available_engineer | A16 |
| Отдельный home_location_id у инженера | /plans/run: HTTP 500 | A10 |

Кейс с домом модифицирует поле в изолированной SQLite напрямую, поскольку публичного API настройки стартов нет. Негативные HTTP-кейсы использовали SQLite, а не PostgreSQL; PostgreSQL проверен основным последовательным flow. Вывод о KeyError также подтверждён вне БД на DTO.

В JSON HTTP-пробы SQLite плановое время `05:48:28` записано без offset: это UTC, сохранённое тестовым адаптером (08:48:28 МСК). Воспроизведение A02 на DTO использует timezone-aware datetime и однозначно показывает 13:00 → 08:10 МСК. На основании SQLite-особенности в этом отчёте не объявляется отдельный timezone-баг production PostgreSQL.

## Проверка реальных входных книг

Применён именно XlsxDatasetImporter и полный HTTP import → plan → approve с demo geocoder/router, 12 seed-инженерами. Числа назначений показывают работоспособность интеграции, **не качество маршрутов по реальной карте**: demo-геокодер создаёт искусственные координаты.

| Регион | Заявки | needs_mapping | Назначены | Неназначены | Инженеров использовано | approve |
|---|---:|---:|---:|---:|---:|---:|
| Восток | 66 | 5 | 58 | 8 | 12 | 200 |
| Юго-восток | 83 | 0 | 75 | 8 | 12 | 200 |
| Югоцентр | 56 | 1 | 55 | 1 | 12 | 200 |

Дата всех книг — 17.08.2026. У всех 205 импортированных requests priority=normal. По текущему mapping распознано 15 аварий. Во всех трёх книгах встретилась пара BK=Подключение / HD=Заказ подключения/Дозаказ оборудования, которую importer определяет как equipment_order/service=20.

## Границы проверки

- Не проверялись реальные 2ГИС scopes/квоты/геометрия/пробки, OSRM/Nominatim live, внешние API и качество геокодирования.
- Не выполнялись Docker build полного API image, CVE scan, ZIP-bomb/DoS, нагрузочные и настоящие конкурентные PostgreSQL-тесты.
- Не измерялось математическое качество отсутствующего внешнего solver или покрытие кода в процентах.
- Не оценивался отсутствующий frontend. Проверялся его текущий API-контракт и соответствующие существующие тесты.
- Из официального PDF извлечены все 9 страниц; страница с таблицей обязательных ограничений также просмотрена визуально. Архивные PDF внутренних созвонов не перепроверялись дословно; использованы Markdown-конспекты. Исходные XLSX не редактировались.
- Авторизация не требовалась для MVP по исходным материалам и не выдана за обязательный недостающий функционал.
- Воспроизводимость результатов привязана к проверенному commit и uv.lock; новый код может и должен изменить результаты негативных проб.

## Git и состав изменений

Локальная ветка `docs/expert-clarifications-audit` создана от актуального dev по `docs/GITFLOW.md`. Сохранены отчёт, матрица 15 требований, доказательства и исходное сообщение экспертов; в документации добавлены ссылки на новые уточнения. Продуктовые исходники/тесты/lock-файл не изменены. Коммиты, push, PR и merge не выполнялись. Существующий untracked `project/.idea/` не затронут.
