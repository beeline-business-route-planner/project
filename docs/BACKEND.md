# Backend: сценарии и действующий API

Эта страница описывает **реализованное** поведение. Целевые требования и ещё не
реализованные идеи лежат в [`backend/docs/user-case/`](../backend/docs/user-case/README.md).
Полная машинная схема запущенного сервера — `/openapi.json`, Swagger UI — `/docs`.
Все бизнес-маршруты имеют префикс `/api`; примеры ниже используют его.

## Рабочий день диспетчера

1. Подготовить на каждый нужный округ две XLSX-книги: заявки и доступных инженеров.
   Загрузить их через `POST /api/planning/initial`. Backend определит роль и округ
   **по содержимому**, проверит пары, геокодирует адреса и построит по каждому округу
   `pending`-план. Другие округа загружать не обязательно.
2. Открыть `GET /api/plans/{id}`: проверить `metrics`, `request_groups`, назначения в
   `engineers[].stops`, неназначенные заявки и причины. Кандидат ещё не меняет текущий
   план. `POST /api/plans/{id}/approve` делает его действующим; `reject` отклоняет.
   Начальный план нужно утвердить до `approval_deadline` (по умолчанию 10 минут).
3. В течение дня обновлять фактические статусы заявок через
   `PATCH /api/requests/{id}/status`. Для обычного перерасчёта вызвать
   `POST /api/planning/replan`, сравнить кандидата с предыдущим планом в `diff`,
   затем утвердить или отклонить.
4. Срочная заявка, отмена заявки, недоступность или возвращение инженера —
   `POST /api/planning/events`. Ответ содержит событие и новый `pending`-план.
   Эффект события применяется **при утверждении** кандидата; отклонение сохраняет
   прежнее состояние. Отмена не выполняется через PATCH статуса.
5. Скачать XLSX конкретной версии через `GET /api/plans/{id}/export` или ZIP с PDF
   дневного отчёта через `GET /api/reports/daily`. API возвращает **подписанный URL**,
   а не байты файла; ссылку нужно открыть до `expires_at`.

Округа независимы: `vostok`, `yugo_vostok`, `yugotsentr`. `current` — последний
утверждённый план нужного округа и дня; `pending` и `rejected` остаются в истории.
Время рабочего дня считается по `Europe/Moscow`. Для первоначального импорта окна
XLSX должны относиться к текущему дню Москвы. В API нет параметра, позволяющего
планировать исторический день как симуляцию.

## Подготовка XLSX

Обе книги `.xlsx` для одного округа должны иметь в `A1` название округа
(Восток, Юго-восток или Югоцентр). Роль определяется по колонкам, а не имени файла.
Файлов — чётное число: одна книга заявок и одна инженеров на каждый загружаемый
округ; дубликаты роли и неполные пары недопустимы. Дополнительные колонки игнорируются.

| Книга | Обязательные заголовки |
|---|---|
| Заявки | `Заявка`, `Тип заявки BK`, `Тип заявки HD`, `Начало`, `Окончание`, `Район`, `Адрес`, `Гигабитное подключение` |
| Инженеры | `Инженер`, `Стартовая точка`, `Начало смены`, `Конец смены`, `Навык 1`, `Тип транспорта` |

В книге заявок также нужна строка адреса офиса: в первой ячейке `Адрес офис...`,
адрес — во второй. `Подключение` и `Навык 2`/`Навык 3` необязательны. Даты окон —
`ДД.ММ.ГГГГ ЧЧ:ММ`, время смены — `ЧЧ:ММ`. Транспорт: автомобиль, пешком, велосипед
или общественный транспорт; точные значения ячеек: `Автомобиль`, `Пешеход`,
`Велосипед`, `Общественный транспорт`.
Приоритет, требуемый навык и оба норматива выводятся из типа заявки по правилам в
`backend/src/api/planning/utils.py`; клиент не присылает их при XLSX-импорте.

| `type_bk` | Приоритет | Полный норматив / работа без дороги, мин | Требуемый навык |
|---|---:|---:|---|
| `global_problem` | 1 | 100 / 80 | `emergency_works` |
| `connection` | 2 | 90 / 70 | `connection_and_orders` |
| `additional_order` | 3 | 40 / 20 | `connection_and_orders` |
| `local_request` | 3 | 50 / 30 | `local_works` |

Координаты адресов определяет DaData; время пути даёт OSRM или 2ГИС согласно
настройке backend. Без рабочих ключей/доступных сервисов импорт может завершиться
ошибкой региона.

## HTTP-контракт

`{id}` — UUID. JSON-поля enum передаются в `snake_case`. Для детального состава
вложенных структур используйте OpenAPI; здесь перечислены поля, нужные клиенту.

| Метод и путь | Вход | Результат |
|---|---|---|
| `POST /api/planning/initial` | `multipart/form-data`: повторяющееся `files` (XLSX); `mode` = `min_engineers` или `balanced` (по умолчанию первое); `strategy` = `lns`, `layered_graph` или `greedy` (по умолчанию `lns`) | `{status, regions:[{region,status,plan_summary,error}]}`; summary: `id`, `planning_date`, `approval_deadline`, mode/strategy, счётчики назначений и пробег |
| `POST /api/planning/replan` | JSON `{regions:[...], mode?, strategy?}`; список непустой, без повторов, опции наследуются от действующего плана | Та же структура по регионам; summary также содержит `based_on_plan_id` |
| `POST /api/planning/events` | JSON события, см. ниже | HTTP 201, `{event_id,event_type,request_id,engineer_id,occurred_at,plan}`; `plan` — summary нового event-replan-кандидата |
| `GET /api/plans/current?region=...&planning_date=YYYY-MM-DD` | `region` обязателен; дата необязательна, по умолчанию сегодня в Москве | Полный утверждённый план или 404 |
| `GET /api/plans?region=...` | Обязательный округ | Массив кратких версий, новые первыми |
| `GET /api/plans/{id}` | UUID версии | Полный снимок версии любого статуса |
| `POST /api/plans/{id}/approve` | Без тела | Краткая версия со статусом `approved`; ошибки конфликта/просрочки — 409 |
| `POST /api/plans/{id}/reject` | Без тела | Краткая версия со статусом `rejected` |
| `GET /api/plans/{id}/export` | UUID версии | `{url,expires_at,filename,content_type,size_bytes}` для XLSX |
| `GET /api/requests/{id}` | UUID заявки | Карточка заявки: внешний ID, тип, адрес/координаты, окно, нормативы, приоритет, навык/транспорт, `status` |
| `PATCH /api/requests/{id}/status` | JSON `{status:"on_the_way"}` | Обновлённая карточка. Допустимы `not_sent`, `sent`, `on_the_way`, `in_progress`, `done`, `overdue`; `cancelled` — только через событие |
| `GET /api/engineers/{id}` | UUID инженера | Карточка: имя, округ, стартовый адрес/координаты, смена, навыки, транспорт, доступность |
| `GET /api/reports/daily?planning_date=YYYY-MM-DD` | Дата обязательна | `{url,expires_at,filename,content_type,size_bytes}` для ZIP с PDF |

`GET /api/plans/{id}` содержит `kind` (`initial`/`replan`/`event_replan`),
`approval_status` (`pending`/`approved`/`rejected`), `is_current`, `can_approve`,
`can_reject`, `calculation_cutoff_at`, ссылки на базовый план/событие, `metrics`,
`baseline_metrics`, `request_groups`, `engineers` и `diff` для сравнения с базой.
Каждая остановка в `engineers[].stops` имеет координаты, порядок, плановое
прибытие/начало/конец, минуты и километры дороги, `is_locked`. Неназначенной
заявке выставляется `unassigned_reason`: `no_matching_skill`,
`no_matching_vehicle`, `no_time_slot`, `no_route` или `no_available_engineer`.
Список `engineers` может включать инженеров без назначенных остановок.

Пример начальной загрузки (реальные файлы должны содержать сегодняшний день):

```bash
curl -F 'files=@requests.xlsx' -F 'files=@engineers.xlsx' \
  -F 'mode=min_engineers' -F 'strategy=lns' \
  http://localhost:8000/api/planning/initial
```

При успешном округе ответ имеет вид
`{"status":"success","regions":[{"region":"vostok","status":"success","plan_summary":{"id":"<uuid>","planning_date":"YYYY-MM-DD",...},"error":null}]}`.
`plan_summary.id` затем передают в `/api/plans/{id}` и `/approve`.

### События

`event_type` принимает `urgent_request`, `request_cancelled`,
`engineer_unavailable`, `engineer_available`. Вместе с `region` нужно передать
**ровно одно** соответствующее поле: `urgent_request`, `request_id` либо
`engineer_id`. Например:

```json
{"region":"vostok","event_type":"engineer_unavailable","engineer_id":"<uuid>"}
```

Для `urgent_request` поле `urgent_request` обязательно содержит `external_id`,
`type_bk`, `type_hd`, `district`, `address`, `is_gigabit`, `window_start`,
`window_end`, `norm_minutes`, `norm_minutes_without_travel`, `priority` (1 или 2),
`required_skill`; опционально `connection_type` и `required_vehicle_type`.
Окно — локальное московское время **без** timezone, например
`2026-09-29T14:00:00`; конец позже начала и оба в текущем рабочем дне, конец окна
должен быть позже текущего времени. Нормативы, приоритет и навык должны точно
совпасть с правилами для `type_bk` в `planning/utils.py`; иначе событие отклоняется.
Для срочного события допускаются только приоритеты 1 или 2. Типы и навыки — enum
из OpenAPI. Событие не заменяет утверждение: после HTTP 201
проверьте `plan.id` и примите решение через `/api/plans/{id}/approve` или `/reject`.

### Ошибки и реальные ограничения

- Обычные ошибки валидации/поиска/конфликта возвращаются с HTTP 422/404/409 и
  `detail`. Ошибка внешнего сервиса может дать 502. У `initial` и `replan` ошибки
  **отдельных округов** находятся в `regions[].error` при HTTP **200**; всегда
  проверяйте верхний `status` и статус каждого округа. Это относится и к части
  ошибок неполной пары XLSX, хотя целевой user case ожидает HTTP 422.
- План может не назначить все заявки: причину смотрите в `request_groups` и
  `unassigned_reason`. Наличие HTTP 200 не означает полного покрытия.
- Backend не отдаёт дорожную геометрию для карты; только последовательность точек,
  время и расстояние. Рисование маршрута по дорогам — отдельный вызов 2ГИС во
  frontend. Ручное планирование описано в
  [отдельном контракте](../backend/docs/MANUAL_PLANNING.md); полного журнала аудита нет.
- `GET /` возвращает `{"ping":"pong"}`, `/metrics` — Prometheus-метрики; они не
  заменяют проверку БД, геокодера, S3 и возможности рассчитать план.

## Где это реализовано

`src/api/planning/` — XLSX, сценарии initial/replan/events; `src/api/plans/` — версии,
решение, diff, экспорт; `src/api/requests/`, `engineers/`, `reports/` — карточки и
отчёт. Модели, enum, репозитории и UnitOfWork — `src/core/db/`; алгоритм —
`src/core/algorithm/`; DaData/маршрутизация/S3 — `src/core/`; провайдеры DI —
`src/core/di/`; конфиг — `src/config/`; миграции — `alembic/`.
Подробная карта слоёв — [архитектура проекта](ARCHITECTURE.md), правила изменения
backend — [`agents-docs`](../backend/agents-docs/ARCHITECTURE.md).
