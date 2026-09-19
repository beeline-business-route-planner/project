# Beeline Business Planning Backend

> Аудит 19.09.2026: [состояние backend и соответствие 15 новым уточнениям](docs/audits/2026-09-19/REPORT.md), [результаты проверок](docs/audits/2026-09-19/VERIFICATION.md), [исходное сообщение экспертов](../docs/source_files/EXPERT_CLARIFICATIONS_2026-09-19.md). Уточнения учтены частично; текущие ограничения перечислены в отчёте.

Модульный backend диспетчерского прототипа: импорт синтетических XLSX, версионированные снимки для
алгоритмов, планирование, утверждение, события/факты, перепланирование, diff, журнал и XLSX/PDF.

## Архитектура

Зависимости направлены внутрь: `presentation → application → domain`; `infrastructure` реализует
порты application. Domain не импортирует FastAPI, SQLAlchemy или httpx. Математическое ядро
заменяется через `PlanningAlgorithm`; встроенный `deterministic-first-fit-v1` — рабочий тестовый
адаптер, а не заявление о качестве оптимизации.

Краткая ER-модель и нормализация: [docs/ER_MODEL.md](docs/ER_MODEL.md). Решения о версиях,
фактах и провайдерах: [docs/ADR.md](docs/ADR.md). Примеры ответов: [docs/API_EXAMPLES.md](docs/API_EXAMPLES.md).
Контракт, CORS и поток для frontend: [docs/FRONTEND_INTEGRATION.md](docs/FRONTEND_INTEGRATION.md).

## Локальный запуск

```bash
cp .env.example .env
docker compose up -d db
uv sync
uv run alembic upgrade head
uv run uvicorn beeline_backend.main:app --reload
```

Альтернативно весь стек запускается одной командой; API-контейнер до старта
автоматически применяет Alembic-миграции:

```bash
docker compose up -d --build
```

OpenAPI: `http://localhost:8000/docs`. Health/readiness: `/api/v1/health`, `/api/v1/readiness`.
Машиночитаемая схема для генерации TypeScript-клиента: `http://localhost:8000/openapi.json`.

Импортируйте только один из файлов вида `Восток Синтетические данные.xlsx`,
`Югоцентр Синтетические данные.xlsx`, `Юго-восток Синтетические данные.xlsx`. Имена с
`Контрольное распределение`, lock-файлы `~$...` и произвольные XLSX отклоняются.

```bash
curl -F 'file=@Dataset/Восток Синтетические данные.xlsx' \
  -H 'Idempotency-Key: demo-east-v1' http://localhost:8000/api/v1/imports
```

CLI для импорта демо-набора после миграции:

```bash
uv run beeline-backend seed-demo 'Dataset/Восток Синтетические данные.xlsx'
```

## API

- `POST /api/v1/imports` — импорт и построчные ошибки.
- `GET /api/v1/scenarios`, `GET /api/v1/requests`, `GET /api/v1/requests/{id}`.
- `GET /api/v1/engineers`, `GET /api/v1/engineers/{id}/route`.
- `POST /api/v1/requests` — новая заявка + идемпотентное событие + предложение перепланирования.
- `POST /api/v1/requests/{id}/facts` — append-only подтверждённый факт.
- `POST /api/v1/plans/run`, `GET /api/v1/planning-runs/{id}`.
- `GET /api/v1/plans`, `GET /api/v1/plans/{id}`, `POST /api/v1/plans/{id}/approve`.
- `POST /api/v1/events` — событие + один новый кандидат.
- `POST /api/v1/plans/{id}/manual-change` — новый полностью пересчитанный черновик.
- `GET /api/v1/plans/diff`, `GET /api/v1/plans/{id}/metrics`.
- `GET /api/v1/audit`, `GET /api/v1/dashboard`.
- `GET /api/v1/plans/{id}/reports/xlsx|pdf`.

## Провайдеры

Конфигурация по умолчанию использует 2ГИС: `GEOCODER_MODE=dgis` для Geocoder API и
`ROUTING_PROVIDER=dgis` для Distance Matrix API и Routing API. Ключ задаётся только через
`DGIS_API_KEY` в локальном `.env`. Матрица направленная, разбивается на блоки до 25 источников
и 25 назначений; недостижимые пары хранятся как `null`. Для выбранных маршрутов запрашивается
детальная геометрия 2ГИС в WKT и преобразуется в GeoJSON `[longitude, latitude]`.

Доступ к Geocoder, Distance Matrix и Routing проверяется независимо. Отсутствующий scope возвращает
диагностируемый `503`, без скрытого fallback на другого провайдера. Лимиты демо-ключа задаются
кабинетом 2ГИС. `nominatim`, `osrm` и `demo` оставлены как явно выбираемые резервные/тестовые адаптеры.
Геокодер проверяет код `meta.code` даже при HTTP 200 и поддерживает оба описанных в OpenAPI
источника координат: `items.point` и WKT `items.geometry.centroid`.

## Frontend и CORS

CORS конфигурируется через `CORS_ORIGINS`, `CORS_ALLOW_METHODS`, `CORS_ALLOW_HEADERS`,
`CORS_EXPOSE_HEADERS`, `CORS_ALLOW_CREDENTIALS` и `CORS_MAX_AGE`. По умолчанию разрешены Vite
(`http://localhost:5173`) и React dev server (`http://localhost:3000`). Ключ 2ГИС остаётся
только на backend и никогда не передаётся в браузер.

## Проверки

```bash
docker compose up -d db
uv sync
uv run ruff check .
uv run mypy src
uv run pytest
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```

`downgrade base` — разрушительная проверка отката: она удаляет схему и все данны. После неё
всегда выполняйте `upgrade head`; на ценной базе проверяйте downgrade только на отдельном тестовом
экземпляре PostgreSQL.

PostgreSQL опубликован на `localhost:55432`, чтобы не конфликтовать с уже установленной локальной БД.

Приложение и миграции по умолчанию используют PostgreSQL 16 через `asyncpg`. SQLite подключён
только в тестах как быстрый изолированный адаптер и не является поддерживаемой production-БД.

## Известные ограничения и точки подключения

- Реальные алгоритмы подключаются реализациями `PlanningAlgorithm`; снимок и валидатор стабильны.
- Входящие факты промышленной FSM подключаются к use case `record_fact`; demo использует ручной API.
- Демо-ключ 2ГИС может не включать все три API и имеет лимиты; приложение проверяет каждую возможность отдельно.
- Demo-маршрутизатор строит геодезические расстояния. Для дорожной геометрии выберите OSRM.
- Фоновая очередь хранится в `outbox_jobs`; текущий прототип исполняет расчёт синхронно после
  транзакционной постановки события. Внешний worker можно добавить без изменения домена/API.
