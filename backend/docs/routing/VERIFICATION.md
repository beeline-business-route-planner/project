# Routing Verification

Документ фиксирует проверку новой routing-архитектуры backend: локальный OSRM, сегментное хранение маршрутов, `detailed`/`overview` geometry, Dragonfly cache и переиспользование сегментов при replanning.

> Важно: этот файл должен содержать только фактические результаты. Значения производительности и количество пройденных тестов нельзя заполнять приблизительно. Сначала выполните команды из разделов ниже, затем внесите реальные результаты в таблицу в конце документа.

## 1. Проверяемая версия

- Базовая ветка: `dev`.
- Базовый commit `dev` на момент создания feature-ветки: `3b8985c77dc41a9fffbb025f1b80fa630dbf178e`.
- Feature-ветка: `feature/routing-cache-osrm`.
- Commit реализации: **заполнить после коммита текущих изменений**.
- Дата проверки: **заполнить при фактическом запуске**.

Проверка Git:

```bash
git branch --show-current
git status
git log --oneline --decorate --graph --all -20
```

Ожидаемая рабочая ветка:

```text
feature/routing-cache-osrm
```

После коммита в этот раздел необходимо вписать:

```bash
git rev-parse HEAD
```

## 2. Что именно проверяется

Новая архитектура должна удовлетворять следующим условиям:

1. Матрица времени/расстояний для planner строится через локальный OSRM.
2. После формирования assignments маршрут каждого инженера разбивается на направленные сегменты.
3. Для отсутствующих сегментов выполняются OSRM Route-запросы.
4. Уже рассчитанные совместимые сегменты переиспользуются.
5. Для каждого инженера сохраняются:
   - `detailed` geometry — полная дорожная геометрия;
   - `overview` geometry — облегчённая геометрия.
6. `overview` строится алгоритмом Douglas–Peucker с допуском в метрах.
7. PostgreSQL остаётся source of truth.
8. Dragonfly используется только как read cache готовых route responses.
9. GET-запросы маршрутов не должны обращаться к OSRM, 2ГИС или геокодеру.
10. Replanning должен пересчитывать только новые/изменившиеся сегменты.
11. 2ГИС не находится на critical path.

## 3. Архитектура, которую проверяем

```mermaid
flowchart TD
    A[Snapshot заявок] --> B[OSRM Table API]
    B --> C[Planner]
    C --> D[Assignments]
    D --> E[RouteBuilder]
    E --> F{Сегмент уже есть?}
    F -->|Да| G[Reuse PostgreSQL route_cache]
    F -->|Нет| H[OSRM Route API]
    H --> I[Сохранить сегмент]
    G --> J[Собрать detailed geometry]
    I --> J
    J --> K[Douglas-Peucker по сегментам]
    K --> L[overview geometry]
    J --> M[plan_route_artifacts]
    L --> M
    M --> N[Dragonfly warm/read cache]
    N --> O[Frontend]
```

Critical path:

```text
OSRM Table -> Planner -> OSRM Route -> PostgreSQL
```

Не critical path:

```text
2GIS
```

## 4. Docker Compose

В Compose должны присутствовать минимум четыре сервиса:

```text
db
api
dragonfly
osrm
```

Проверка:

```bash
cd backend
OSRM_DATA_DIR=/absolute/path/to/prepared/osrm/data docker compose config --services
```

Ожидаемый результат:

```text
db
api
dragonfly
osrm
```

Также проверить валидность Compose:

```bash
OSRM_DATA_DIR=/absolute/path/to/prepared/osrm/data docker compose config --quiet
```

### Порты локальной разработки

По текущей конфигурации:

| Сервис | Порт хоста |
| --- | ---: |
| Backend API | `8000` |
| PostgreSQL | `55432` |
| OSRM | `5000` |
| Dragonfly | `56379` |

OSRM внутри docker-сети доступен backend по:

```text
http://osrm:5000
```

Dragonfly внутри docker-сети:

```text
redis://dragonfly:6379/0
```

## 5. Подготовка локального OSRM

Большой `.osm.pbf` и подготовленный graph не должны храниться в Git.

Из `backend`:

```bash
python3 scripts/prepare_osrm.py \
  --url https://download.bbbike.org/osm/bbbike/Moscow/Moscow.osm.pbf
```

Или для уже скачанного файла:

```bash
python3 scripts/prepare_osrm.py \
  --pbf /absolute/path/Moscow.osm.pbf
```

Скрипт должен подготовить MLD graph через:

```text
osrm-extract
osrm-partition
osrm-customize
```

После успешной подготовки сохранить выведенный путь:

```env
OSRM_DATA_DIR=/absolute/path/to/prepared/graph
```

Проверить наличие manifest:

```bash
cat "$OSRM_DATA_DIR/manifest.json"
```

Он нужен для fingerprint графа и корректного reuse сегментов.

## 6. Запуск инфраструктуры

```bash
cd backend
docker compose up -d --build
docker compose ps
```

Все четыре сервиса должны перейти в healthy/running состояние.

Проверить API:

```bash
curl -s http://127.0.0.1:8000/api/v1/readiness | python3 -m json.tool
```

Ожидается:

```json
{
  "status": "ready"
}
```

Проверить Dragonfly:

```bash
docker compose exec dragonfly redis-cli ping
```

Ожидается:

```text
PONG
```

Проверить OSRM напрямую:

```bash
curl -s "http://127.0.0.1:5000/nearest/v1/driving/37.6173,55.7558" \
  | python3 -m json.tool
```

Ожидается `code: "Ok"` и waypoint.

## 7. Проверка OSRM Matrix

Матрица planner должна строиться через OSRM Table API, а не через 2ГИС.

Пример ручной проверки:

```bash
curl -s \
  "http://127.0.0.1:5000/table/v1/driving/37.6173,55.7558;37.6310,55.7650?annotations=duration,distance" \
  | python3 -m json.tool
```

Ожидается:

```json
{
  "code": "Ok",
  "durations": [...],
  "distances": [...]
}
```

В application flow matrix provider должен быть `osrm`.

## 8. Миграции

Новая миграция:

```text
0002_route_artifacts
```

Она должна:

- добавить `route_legs.route_cache_id`;
- создать FK на `route_cache` с `ON DELETE RESTRICT`;
- создать таблицу `plan_route_artifacts`;
- хранить для `(plan_id, engineer_id)`:
  - `revision`;
  - `detailed`;
  - `overview`.

Проверка:

```bash
uv run alembic upgrade head
uv run alembic check
```

Для отдельной тестовой PostgreSQL-БД:

```bash
uv run python scripts/verify_postgres_migrations.py \
  --server-url postgresql://beeline:beeline@127.0.0.1:55432/postgres
```

Не выполнять downgrade на рабочей пользовательской БД.

## 9. Автоматические тесты

Запустить из `backend`:

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run mypy src
```

После выполнения заполнить фактические значения:

| Проверка | Фактический результат |
| --- | --- |
| `pytest` | **заполнить** |
| `ruff` | **заполнить** |
| `mypy` | **заполнить** |
| PostgreSQL migration verification | **заполнить** |

Новая routing-suite должна покрывать как минимум:

- `tests/test_osrm.py`;
- `tests/test_route_artifacts.py`;
- `tests/test_route_cache_and_migrations.py`;
- `tests/test_route_read_api.py`;
- `tests/test_hybrid_providers.py`.

### Что проверяют regression-тесты route artifacts

В `test_route_artifacts.py` зафиксирован сценарий reuse:

```text
initial:
segments_calculated = 3

replan с новой промежуточной точкой:
segments_reused = 2
segments_calculated = 2

повторное построение того же маршрута:
segments_reused = 4
segments_calculated = 0
```

Также тестируется, что `overview` содержит меньше точек, чем `detailed` для подходящей геометрии.

## 10. Проверка initial planning

Для ручного smoke test можно использовать существующий scenario или специальный `scripts/routing_demo.py`.

Если используется уже импортированный scenario:

```bash
curl -sS -X POST "http://127.0.0.1:8000/api/v1/plans/run" \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "<SCENARIO_ID>",
    "planning_date": "<YYYY-MM-DD>",
    "base_plan_id": null,
    "as_of": null
  }' | python3 -m json.tool
```

Ожидается:

```json
{
  "planning_run_id": "...",
  "plan_id": "...",
  "status": "succeeded"
}
```

Сохранить `plan_id` для последующих проверок.

## 11. Overview API

Endpoint:

```text
GET /api/v1/plans/{plan_id}/routes
```

Команда:

```bash
curl -s "http://127.0.0.1:8000/api/v1/plans/$PLAN_ID/routes" \
  | python3 -m json.tool
```

Endpoint должен вернуть облегчённые маршруты всех инженеров.

Для каждого маршрута проверить:

- `engineer_id`;
- `route_status`;
- `geometry`;
- `provider`;
- distance/duration;
- revision/status плана.

Именно этот endpoint должен использовать frontend после открытия утверждённого плана, чтобы показать все маршруты одновременно.

## 12. Detailed API выбранного инженера

Endpoint:

```text
GET /api/v1/plans/{plan_id}/engineers/{engineer_id}/route
```

Команда:

```bash
curl -s \
  "http://127.0.0.1:8000/api/v1/plans/$PLAN_ID/engineers/$ENGINEER_ID/route" \
  | python3 -m json.tool
```

Ответ должен содержать:

- `engineer_id`;
- `plan_id`;
- detailed `geometry`;
- ordered `stops`;
- `segments`;
- total distance;
- total duration;
- provider;
- graph fingerprint/revision metadata.

Этот endpoint вызывается при выборе инженера на карте.

## 13. Проверка двух уровней детализации

Для одного и того же инженера:

```text
overview.geometry.coordinates
```

должно содержать не больше точек, чем:

```text
detailed.geometry.coordinates
```

`overview` строится не отдельным routing-запросом, а из уже сохранённого `detailed`.

Алгоритм:

```text
detailed segment
      ↓
Douglas–Peucker
      ↓
overview segment
```

Допуск по умолчанию:

```env
ROUTE_OVERVIEW_TOLERANCE_METERS=20
```

Упрощение выполняется отдельно для каждого сегмента, поэтому начало и конец сегмента сохраняются.

## 14. Проверка Dragonfly cache

Текущие ключи:

```text
routes:v1:plan:{plan_id}:revision:{revision}:overview
routes:v1:plan:{plan_id}:revision:{revision}:engineer:{engineer_id}:detailed
```

TTL по умолчанию:

```text
21600 секунд
```

Timeout Dragonfly:

```text
0.25 секунды
```

### Cache miss

Удалить только route keys выбранного плана:

```bash
docker compose exec dragonfly redis-cli --scan \
  --pattern "routes:v1:plan:${PLAN_ID}:*"
```

При необходимости удалить найденные ключи и выполнить GET.

Первый запрос должен:

```text
Dragonfly miss
    ↓
PostgreSQL
    ↓
Dragonfly set
    ↓
response
```

### Cache hit

Повторить тот же GET.

Он должен прочитать готовый response из Dragonfly после короткой проверки revision/status в PostgreSQL.

## 15. PostgreSQL — source of truth

Dragonfly не должен быть единственным местом хранения маршрута.

Проверка:

```bash
docker compose exec dragonfly redis-cli FLUSHDB
```

После этого повторить:

```bash
curl -s "http://127.0.0.1:8000/api/v1/plans/$PLAN_ID/routes" >/dev/null
```

и detailed endpoint.

Оба запроса должны успешно отработать, восстановив response из PostgreSQL и снова заполнив Dragonfly.

Это подтверждает:

```text
PostgreSQL = source of truth
Dragonfly      = cache
```

## 16. GET не должен вызывать routing provider

Это обязательный acceptance criterion.

После создания плана все route artifacts уже рассчитаны и сохранены.

Повторные запросы:

```text
GET /plans/{id}/routes
GET /plans/{id}/engineers/{engineer_id}/route
```

не должны вызывать:

- OSRM Table;
- OSRM Route;
- 2ГИС;
- geocoder.

Это покрывается API regression-тестами, где routing provider заменяется реализацией, падающей при вызове, а GET endpoints продолжают успешно отдавать сохранённые маршруты.

Для ручной проверки можно сравнить логи API до и после серии GET и убедиться, что новые `routing_request service=route/table` не появляются.

## 17. Проверка segment reuse при replanning

Концептуальный пример:

Исходный маршрут:

```text
Office -> A -> B -> C
```

После replanning:

```text
Office -> A -> X -> B -> C
```

Переиспользуются:

```text
Office -> A
B -> C
```

Рассчитываются заново только:

```text
A -> X
X -> B
```

Segment signature направленный и зависит минимум от:

- provider;
- graph fingerprint;
- routing profile;
- origin;
- destination;
- routing options;
- версии формата ключа.

`A -> B` и `B -> A` — разные сегменты.

После replanning проверить diagnostics planning run:

```text
segments_reused
segments_calculated
```

Для точечного изменения ожидается, что `segments_reused > 0`, а `segments_calculated` меньше общего числа сегментов нового маршрута.

## 18. Проверка сохранения старого плана

Новый replan не должен мутировать geometry старой версии плана.

После создания нового plan повторно запросить:

```bash
GET /api/v1/plans/{OLD_PLAN_ID}/routes
```

и сравнить с response, сохранённым до replanning.

Ожидается идентичный список route artifacts для старой версии.

Новая версия плана должна иметь собственные revision/cache keys.

## 19. Проверка изоляции 2ГИС

Основной routing-контур не должен зависеть от 2ГИС.

Для проверки оставить:

```env
ROUTING_PROVIDER=osrm
```

и удалить/испортить `DGIS_API_KEY`.

При заранее известных координатах planning/replanning должны продолжать работать через local OSRM.

Ожидается:

```text
matrix provider = osrm
route provider = osrm
plan status = succeeded
```

Таким образом ошибки 2ГИС `403`, `429`, `5xx`, timeout или исчерпание квоты не блокируют planning.

## 20. Сквозной demo / benchmark

В проекте предусмотрен:

```text
scripts/routing_demo.py
```

Он создаёт синтетический сценарий с известными координатами дорог Москвы, поэтому live geocoder для benchmark не нужен.

Скрипт проверяет:

- import;
- initial plan;
- overview;
- detailed routes;
- cold/warm route reads;
- approve;
- повторный plan;
- urgent request/replan;
- сохранность old plan geometry;
- diagnostics `segments_reused` / `segments_calculated`;
- размер detailed/overview;
- p50/p95 чтения.

Запускать только против локальной disposable development database, не production:

```bash
uv run python scripts/routing_demo.py \
  --database-url postgresql+asyncpg://beeline:beeline@127.0.0.1:55432/beeline \
  --api-url http://127.0.0.1:8000 \
  --osrm-url http://127.0.0.1:5000 \
  --dragonfly-url redis://127.0.0.1:56379/0 \
  --repeats 30 \
  --output routing-demo-results.json
```

> Важно: указанная `beeline` БД должна быть локальной тестовой/dev-БД, данные которой можно изменять. Не использовать production database.

Скрипт выводит JSON и сохраняет его в `routing-demo-results.json`.

## 21. Метрики, которые нужно зафиксировать

После запуска `routing_demo.py` перенести значения из JSON сюда.

| Метрика | Фактическое значение |
| --- | ---: |
| Planning date | **заполнить** |
| Scenario ID | **заполнить** |
| Plan ID | **заполнить** |
| Engineers/routes | **заполнить** |
| Detailed coordinates | **заполнить** |
| Overview coordinates | **заполнить** |
| Detailed comparable JSON bytes | **заполнить** |
| Overview comparable JSON bytes | **заполнить** |
| Payload reduction | **заполнить %** |
| Actual overview response bytes | **заполнить** |
| Overview cold read p50 | **заполнить ms** |
| Overview cold read p95 | **заполнить ms** |
| Overview warm read p50 | **заполнить ms** |
| Overview warm read p95 | **заполнить ms** |

Также записать diagnostics всех routing runs:

| Run | `segments_reused` | `segments_calculated` |
| --- | ---: | ---: |
| Initial plan | **заполнить** | **заполнить** |
| Rebuild/base plan | **заполнить** | **заполнить** |
| Urgent replan | **заполнить** | **заполнить** |

Не использовать придуманные значения.

## 22. Логи и observability

Во время planning/replanning проверить структурированные события:

```text
routing_request
route_build
plan_routes_persisted
route_cache
http_request
```

Для `route_build` должны присутствовать как минимум:

```text
segments_reused
segments_calculated
graph_fingerprint
engineers
input_version
```

Для демонстрации особенно полезна строка вида:

```text
segments_total = N
segments_reused = X
segments_calculated = Y
```

где при небольшом replanning `X` заметно больше нуля.

## 23. Поведение при отказе Dragonfly

Dragonfly не является обязательным для корректности.

Проверка:

```bash
docker compose stop dragonfly
```

После этого выполнить overview и detailed GET.

Ожидается:

- API продолжает отвечать;
- данные читаются из PostgreSQL;
- ошибка Dragonfly не превращается в 5xx route endpoint.

После проверки:

```bash
docker compose start dragonfly
```

## 24. Поведение при отказе OSRM после расчёта плана

После того как plan уже создан и route artifacts сохранены:

```bash
docker compose stop osrm
```

Повторить:

```text
GET /plans/{id}/routes
GET /plans/{id}/engineers/{engineer_id}/route
```

Ожидается успешный ответ, потому что read path не должен обращаться к routing provider.

Новый planning/replanning без OSRM, напротив, должен завершиться контролируемой ошибкой внешней зависимости, а не создавать частично сохранённый готовый plan.

После проверки:

```bash
docker compose start osrm
```

## 25. Известные ограничения

1. OSRM использует статический дорожный граф и не предоставляет live traffic.
2. Подготовленный `car.lua` graph покрывает driving, но не public transit/walking.
3. Покрытие маршрутов зависит от выбранного `.osm.pbf` bbox.
4. Dragonfly — best-effort cache; eviction допустим.
5. Дедупликация одновременных одинаковых routing calls гарантируется внутри процесса; между несколькими API replicas возможны повторные внешние вызовы, при этом уникальность хранения защищает БД.
6. Segment reuse корректен только при совпадающем graph fingerprint/profile/options/координатах.
7. `overview` уменьшает объём geometry, но конкретный процент зависит от формы реального маршрута и tolerance.
8. Старые legacy plans без `plan_route_artifacts` не перестраиваются скрыто на GET; для них возможен `409 route_artifacts_unavailable`.
9. Frontend в routing-задаче не реализуется backend-изменениями; backend предоставляет два специализированных read API.

## 26. Статическая проверка текущего архива

При ревью исходников новой реализации подтверждено наличие:

- локального `osrm` service в Docker Compose;
- Dragonfly service;
- `scripts/prepare_osrm.py`;
- `scripts/routing_demo.py`;
- миграции `0002_route_artifacts`;
- `RouteBuilder` с segment reuse;
- Douglas–Peucker simplification;
- `plan_route_artifacts`;
- Dragonfly read-through cache;
- overview/detailed API;
- тестов route artifacts/cache/read API/OSRM.

Также выполнены без ошибок:

```text
git diff --check
python -m compileall src tests scripts alembic
```

Полный `pytest` в среде ревью не был выполнен из-за отсутствия сетевого доступа для скачивания lock-зависимостей (`pydantic-core`). Это ограничение среды ревью и **не считается подтверждением прохождения тестов**. Финальное значение `pytest passed` необходимо получить локально по командам из раздела 9.

## 27. Итоговый checklist

После фактического локального прогона отметить выполненные пункты:

- [ ] `feature/routing-cache-osrm` содержит commit новой реализации.
- [ ] `docker compose config --quiet` проходит.
- [ ] `db`, `api`, `dragonfly`, `osrm` запущены.
- [ ] OSRM `nearest` работает.
- [ ] OSRM Table работает.
- [ ] `alembic upgrade head` проходит.
- [ ] PostgreSQL migration verification проходит.
- [ ] `pytest` проходит.
- [ ] `ruff` проходит.
- [ ] `mypy` проходит.
- [ ] Initial plan возвращает `status=succeeded`.
- [ ] Overview API отдаёт все маршруты.
- [ ] Detailed API отдаёт выбранного инженера.
- [ ] Overview содержит меньше либо столько же координат, чем detailed.
- [ ] Повторные GET не вызывают OSRM.
- [ ] Dragonfly cache hit подтверждён.
- [ ] После `FLUSHDB` данные восстанавливаются из PostgreSQL.
- [ ] При остановленном Dragonfly read API продолжает работать.
- [ ] При остановленном OSRM уже сохранённые routes продолжают читаться.
- [ ] Replanning показывает `segments_reused > 0` для частичного изменения маршрута.
- [ ] Старый plan остаётся неизменным после replan.
- [ ] Planning работает без 2ГИС при `ROUTING_PROVIDER=osrm`.
- [ ] `routing_demo.py` сформировал реальные benchmark metrics.
- [ ] В этот документ внесены фактические значения, без придуманных цифр.

## 28. Критерий готовности к демонстрации

Routing-контур готов к демонстрации, когда можно последовательно показать:

```text
1. docker compose ps
2. local OSRM healthy
3. planning -> succeeded
4. все overview routes на карте
5. выбор инженера -> detailed route
6. повторный выбор -> без routing request
7. urgent request / replan
8. segments_reused > 0
9. новая версия маршрута отображается
10. старая версия плана остаётся доступна
```

Для защиты ключевая формулировка архитектуры:

> Массовый расчёт матрицы и маршрутов выполняется собственным OSRM без внешних квот. Маршруты рассчитываются один раз после planning/replanning и сохраняются в PostgreSQL. Для общей карты backend отдаёт облегчённую geometry, для выбранного инженера — full geometry. Dragonfly ускоряет чтение, но не является источником истины. При replanning неизменившиеся сегменты переиспользуются, поэтому OSRM вызывается только для новых переходов. 2ГИС сохранён как дополнительный provider и не находится на critical path.
