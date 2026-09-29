# Архитектура и навигация по проекту

Это текущая реализация, не ранний план из `team_discussions/`. В развёртывании есть
один FastAPI backend и отдельный React frontend. Алгоритм — Python-пакет внутри
backend, не сетевой сервис. PostgreSQL и MinIO запускаются через Compose; DaData,
OSRM и 2ГИС — внешние интеграции.

## Путь данных

1. Диспетчер загружает XLSX через frontend или `POST /api/planning/initial`.
2. `backend/src/api/planning/parser.py` определяет округ и роль книг по содержимому,
   проверяет строки и выводит норматив/приоритет/навык из типа заявки.
3. `PlanningService` геокодирует адреса, сохраняет исходные книги в S3, а заявки,
   инженеров и метаданные — в PostgreSQL. `AlgorithmService` запрашивает через
   `TravelMatrixService` матрицы OSRM либо 2ГИС и рассчитывает initial + baseline.
4. Pending-план записывается как версия. Утверждение делает его рабочим; отклонение
   оставляет только в истории. Replan и события строятся от последнего approved-плана.
5. Frontend читает сохранённый снимок плана и карточки; для **выбранного** инженера
   2ГИС Directions рисует дорогу между точками. Backend хранит остановки и время пути,
   но не отдаёт полилинию дороги.

Полное описание поведения и форм HTTP: [backend](BACKEND.md). Экраны и режимы
frontend: [frontend](FRONTEND.md).

## Где искать код

| Задача | Путь |
|---|---|
| Сборка FastAPI, DI, middleware, `/`, `/metrics` | `backend/src/main.py` |
| HTTP-маршруты и Pydantic-схемы | `backend/src/api/<domain>/router.py`, `schemas.py` |
| Бизнес-сценарий и транзакция | `backend/src/api/<domain>/service.py` |
| Разбор Excel / сборка сложного ответа | `backend/src/api/planning/parser.py`, `backend/src/api/plans/presenter.py` |
| Модели, репозитории, UnitOfWork, enum | `backend/src/core/db/` |
| Алгоритм, стратегии и аудит результата | `backend/src/core/algorithm/` |
| Клиенты и сервисы внешних API | `backend/src/core/{geocoding,routing,dgis,s3}/` |
| Выбор поставщика матриц | `backend/src/core/travel_matrix/` |
| Сборка зависимостей | `backend/src/core/di/` |
| Конфиг и миграции | `backend/src/config/`, `backend/alembic/` |
| Frontend API и типы | `frontend/src/api/` |
| Загрузка/адаптация данных и действия | `frontend/src/hooks/usePlanner.ts` |
| Экраны и карта | `frontend/src/pages/`, `frontend/src/components/MapPanel.tsx` |
| Инфраструктура | `backend/docker-compose.yml`, `backend/deploy/` |

Backend-домены: `planning` создаёт версии, `plans` читает/утверждает/экспортирует,
`requests` читает и меняет статус, `engineers` читает инженера, `reports` создаёт
дневной архив. Поток зависимостей: router → domain service → UnitOfWork/repository →
PostgreSQL; domain service также вызывает независимые core-сервисы. `dishka` передаёт
зависимости; роутер не работает с БД напрямую. Правила изменения backend подробно
описаны в [его архитектурных инструкциях](../backend/agents-docs/ARCHITECTURE.md).

## Состояние и время

- `Plan` хранит полный снимок одного округа и дня (`initial`, `replan`, `event_replan`).
  `pending`/`rejected` не подменяют текущий `approved`.
- `PlanStop` хранит порядок, плановое прибытие/начало/конец, минуты дороги и километры;
  `PlanUnassignedRequest` — причину неназначения. Baseline хранится отдельно от планов.
- Рабочий день и cutoff расчёта — Москва (`Europe/Moscow`); публичный endpoint не
  принимает произвольный clock для симуляции. Время создания/решения API сериализует
  в UTC, окно срочной заявки передаётся локальным временем Москвы без timezone.
- Оригинальные XLSX хранятся в S3-бакете загрузок с метаданными в БД. Временные
  экспорты имеют отдельный бакет/префикс и выдаются по подписанной ссылке.

Техническая карта backend — [PROJECT_CONTEXT.md](../backend/agents-docs/PROJECT_CONTEXT.md).
Целевое продуктовое поведение — [user cases](../backend/docs/user-case/README.md).
Если описание расходится с кодом, для фактического API проверяйте код и `/openapi.json`.
