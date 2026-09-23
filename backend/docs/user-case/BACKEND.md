# Backend-контракт жизненного цикла планов

## 1. Граница документа

Документ переводит [`FULL_USER_CASE.md`](./FULL_USER_CASE.md) в требования к backend.
Он не предписывает конкретную миграцию или порядок коммитов, но фиксирует целевую модель,
транзакционные границы, API и проверки. При реализации обязательно соблюдать общие
архитектурные правила проекта.

## 2. Доменные enum

### 2.1 `PlanKind`

```text
initial
replan
event_replan
```

Старое значение/имя `manual_replan` заменяется на `replan` согласованной миграцией.

### 2.2 `ApprovalStatus`

Единый закрытый словарь для планов и событий:

```text
pending
approved
rejected
```

### 2.3 `ReplanningEventType`

```text
urgent_request
request_cancelled
engineer_unavailable
engineer_available
```

## 3. Целевая модель данных

### 3.1 `Plan`

Необходимые поля:

| Поле | Назначение |
|---|---|
| `id` | UUID плана. |
| `region` | Округ. |
| `planning_date` | Рабочий день по Москве. |
| `upload_id` | Версия исходных данных рабочего дня. |
| `kind` | `initial/replan/event_replan`. |
| `approval_status` | `pending/approved/rejected`. |
| `based_on_plan_id` | База replan/event replan; `null` у initial. |
| `triggered_by_event_id` | Событие event replan; иначе `null`. |
| `calculation_cutoff_at` | Временной срез, относительно которого алгоритм фиксировал прошлое. |
| `created_at` | Время завершения расчёта/сохранения. |
| `approved_at` | Время утверждения, только для approved. |
| `rejected_at` | Время отклонения/вытеснения/протухания, только для rejected. |
| `total_mileage_km` | Общий пробег. |
| `engineers_used_count` | Задействованные инженеры. |
| `assigned_requests_count` | Назначенные заявки. |
| `unassigned_requests_count` | Неназначенные заявки. |

`is_baseline` удаляется полностью. Baseline не является разновидностью `Plan`.

Constraints:

- initial: `based_on_plan_id is null`, `triggered_by_event_id is null`;
- replan: `based_on_plan_id is not null`, `triggered_by_event_id is null`;
- event replan: оба FK заполнены;
- `approved_at` заполнено только при `approved`;
- `rejected_at` заполнено только при `rejected`;
- `approved_at` и `rejected_at` не заполнены одновременно;
- базовый план имеет тот же `region` и `planning_date`;
- событие имеет тот же `region` и `planning_date`.

Текущий план нельзя определять по `created_at`. Репозиторий выбирает последний approved по
`approved_at DESC, id DESC` для пары `region + planning_date`.

### 3.2 `ReplanningEvent`

Необходимые поля:

| Поле | Назначение |
|---|---|
| `id` | UUID события. |
| `region` | Единственный затронутый округ. |
| `planning_date` | Рабочий день. |
| `event_type` | Тип события. |
| `approval_status` | Всегда согласован со связанным планом. |
| `request_id` | Для срочной заявки/отмены. |
| `engineer_id` | Для недоступности/возвращения инженера. |
| `created_at` | Одновременно фактическое время события в MVP. |
| `approved_at` | Когда событие применено. |
| `rejected_at` | Когда событие отклонено. |

Пользовательское `occurred_at` из HTTP-контракта удаляется на MVP. Если колонка остаётся
технически, backend заполняет её значением server now и не принимает извне.

Для event replan нужна однозначная связь один-к-одному между pending-событием и планом.
Один pending-event на `region + planning_date` обеспечивается транзакционной проверкой и,
если схема позволяет, частичным уникальным индексом.

### 3.3 `BaselineResult`

Отдельная таблица сравнения, не наследующая жизненный цикл `Plan`:

| Поле | Назначение |
|---|---|
| `id` | UUID результата. |
| `initial_plan_id` | Unique FK на initial-кандидат. |
| `assigned_requests_count` | Назначенные baseline. |
| `unassigned_requests_count` | Неназначенные baseline. |
| `engineers_used_count` | Задействованные baseline. |
| `total_mileage_km` | Пробег baseline. |
| `average_workload_with_travel` | Средняя загрузка с дорогой. |
| `average_workload_without_travel` | Средняя загрузка без дороги. |
| `algorithm_version` | Версия контрольной реализации. |
| `created_at` | Время расчёта. |

Baseline строит маршруты в памяти, но baseline stops в рабочие таблицы не записывает.

### 3.4 `Request`

Для согласованного approve-check требуется текущее поле `status`, использующее
`RequestStatus`. `updated_at` уже существует и обновляется при изменении статуса или
значимых данных заявки.

Повторный initial upload до утверждения означает версии входных данных. Поэтому глобальная
уникальность `external_id` должна быть пересмотрена: идентичные внешние номера допустимы в
разных `DataUpload`. Целевой смысл уникальности — в рамках версии входных данных.

Срочная заявка event replan не принадлежит утреннему upload; её идентичность и проверка
дубликата должны быть определены отдельно от scoped-уникальности импортированных строк.

### 3.5 `PlanStop`

Существующие замороженные значения сохраняются. `is_locked = true` означает точную копию
прошедшей/начатой остановки базового плана. Для locked stop должны совпадать:

- `engineer_id`;
- `request_id`;
- `sequence_number` в уже прожитой части;
- arrival/start/finish;
- travel minutes/distance;
- наблюдаемая семантика назначения.

### 3.6 Исходные и экспортные файлы

`UploadedFile` продолжает хранить метаданные постоянных исходных Excel. Временные экспорты
XLSX/PDF/ZIP не создают строки в PostgreSQL и живут в отдельном S3-префиксе.

## 4. Репозитории

Нужны именованные операции без прямого SQL из сервисов:

### `PlanRepository`

- `get_current(region, planning_date)`;
- `list_by_region(region)`;
- `get_with_lock(plan_id)` для approve/reject;
- `list_pending(region, planning_date, exclude_plan_id)`;
- `reject_pending(...)`;
- `has_approved_initial(region, planning_date)`;
- `create(...)`;
- методы загрузки данных плана для presenter/diff.

### `ReplanningEventRepository`

- `get_pending(region, planning_date)`;
- `get_latest_approved_for_engineer(engineer_id, planning_date)`;
- проверка утверждённой отмены заявки;
- проверка утверждённой срочной заявки;
- создание и смена статуса под контролем сервиса.

### `BaselineResultRepository`

- `create`;
- `get_by_initial_plan_id`.

Проверки состояния, включающие несколько сущностей, остаются в доменном сервисе, а не
переносятся в репозиторий как скрытая бизнес-логика.

## 5. Сервисы и ответственность

### 5.1 Planning service

Оркестрирует:

- import initial;
- replan нескольких округов;
- создание события и event replan;
- региональную изоляцию ошибок;
- перевод ошибок core-подсистем в API-доменные исключения.

### 5.2 Plan service

Отвечает за:

- чтение current/history/detail;
- approve/reject;
- согласование статусов плана и события;
- конкурентную блокировку;
- проверку позднего approve;
- автоматическое отклонение остальных pending;
- подготовку данных для diff presenter.

### 5.3 Diff presenter

Чисто и детерминированно сравнивает два уже загруженных плана. Не выполняет I/O и не
сохраняет результат.

### 5.4 Export/report services

Генерируют бинарные данные, передают их S3 storage и возвращают DTO временной ссылки.
Экспорт не меняет план и не открывает транзакцию записи доменных сущностей.

## 6. HTTP API

Имена схем иллюстративны; формы и поведение обязательны.

### 6.1 `POST /api/planning/initial`

Multipart с парами Excel. Синхронно ждёт импорт и расчёт. По каждому округу возвращает:

```json
{
  "region": "east",
  "status": "success",
  "plan_summary": {
    "id": "uuid",
    "kind": "initial",
    "approval_status": "pending",
    "planning_date": "2026-09-22",
    "created_at": "...",
    "approval_deadline": "...",
    "assigned_requests_count": 80,
    "unassigned_requests_count": 20,
    "engineers_used_count": 9,
    "total_mileage_km": "123.45"
  }
}
```

Если для региона уже есть approved initial за день, регион получает конфликт. Другие
регионы того же запроса могут завершиться успешно.

### 6.2 `POST /api/planning/replan`

JSON со списком уникальных округов. Для каждого находит current и возвращает региональный
summary/error. Не принимает Excel и не создаёт события.

### 6.3 `POST /api/planning/events`

Принимает ровно одно событие одного округа. Для срочной заявки содержит полный payload
новой заявки; для остальных — целевой ID. `occurred_at` извне не принимается.

Событие и план либо оба сохранены, либо оба отсутствуют. Ответ содержит summary созданного
event replan.

### 6.4 `POST /api/plans/{plan_id}/approve`

Без тела. Повторный approve не идемпотентен и отвечает конфликтом. Успех возвращает
обновлённый summary/current metadata. Полный план можно перечитать отдельным GET.

### 6.5 `POST /api/plans/{plan_id}/reject`

Без тела и причины. Разрешён только для pending.

### 6.6 `GET /api/plans/current`

Query:

- `region` — обязательный;
- `planning_date` — опциональный, default = сегодня по Москве.

Возвращает только approved current. Pending никогда не подменяет current.

### 6.7 `GET /api/plans?region=...`

Возвращает summaries всех статусов, новые сверху. Обязательный фильтр — только округ.

### 6.8 `GET /api/plans/{plan_id}`

Возвращает полную карточку. Поля lifecycle добавляются к старому контракту:

- `planning_date`;
- `approval_status`;
- `approved_at/rejected_at`;
- `is_current`;
- counts/load metrics;
- `diff`, равный `null` у initial.

`is_baseline` удаляется.

### 6.9 `GET /api/plans/{plan_id}/export`

Генерирует XLSX, загружает в S3 и возвращает presigned URL с временем истечения.

### 6.10 `GET /api/reports/daily?planning_date=...`

Генерирует PDF каждого доступного округа и общий summary, упаковывает ZIP, загружает в S3
и возвращает временную ссылку. Допускается вызов в середине дня.

## 7. Мультиокружный ответ

Для initial/replan:

```json
{
  "status": "partial_success",
  "regions": [
    {
      "region": "east",
      "status": "success",
      "plan_summary": {}
    },
    {
      "region": "south_east",
      "status": "error",
      "error": {
        "code": "routing_unavailable",
        "detail": "Не удалось построить маршрут округа"
      }
    }
  ]
}
```

Региональная ошибка не должна раскрывать адреса, содержимое файла, ответ провайдера или
внутренний traceback.

## 8. Транзакционные границы

### 8.1 Initial

Импорт одного округа и сохранение его кандидата должны иметь явно определённую семантику.
Мультиокружный запрос не является общей атомарной транзакцией: успешные округа остаются.

Исходные S3-upload требуют существующей компенсации при DB-сбое.

### 8.2 Event replan

Одна транзакция PostgreSQL включает:

- создание события;
- создание срочной заявки, если применимо;
- Plan/PlanStop/PlanUnassignedRequest;
- status `pending` обеих сущностей.

Любая ошибка до commit откатывает всё. Внешние вызовы маршрутизации выполняются с учётом
того, что нельзя считать их частью транзакции.

### 8.3 Approve

Транзакция с блокировками:

1. lock кандидата;
2. lock/повторное чтение current;
3. проверки lifecycle и фактической согласованности;
4. approve кандидата;
5. применение event-state, если есть;
6. reject остальных pending округа/дня;
7. commit.

Два параллельных approve одного округа не могут оба завершиться успехом.

### 8.4 Reject

Lock кандидата, проверка pending, согласованный reject события, commit.

## 9. Проверка позднего approve

### Initial

Точная проверка актуальности initial пока требует отдельного проектирования. Фиксированные
10 минут не являются окончательным доменным правилом. Если более точный критерий не будет
согласован до реализации, временный MVP-fallback выглядит так:

```text
now <= created_at + initial_approval_ttl
```

В fallback-варианте TTL берётся из typed config и равен 10 минутам; литералом в сервисе
его не задают.

### Replan/event replan

Approve запрещён, если:

- current.id отличается от `based_on_plan_id`;
- после created/cutoff появилось утверждённое событие округа;
- `Request.updated_at` затронутой заявки новее кандидата;
- статус затронутой заявки изменился;
- availability инженера изменилась;
- дифф пытается изменить stop, эффективное время которого уже наступило.

Полностью неизменённая locked-часть прошлого допустима.

## 10. Дифф DTO

Рекомендуемая форма:

```json
{
  "base_plan_id": "uuid",
  "candidate_plan_id": "uuid",
  "metrics": {
    "before": {},
    "after": {},
    "delta": {}
  },
  "engineers": [
    {
      "engineer_id": "uuid",
      "change": "changed",
      "before": {},
      "after": {},
      "requests": [
        {
          "request_id": "uuid",
          "changes": ["reassigned", "rescheduled", "travel_changed"],
          "before": {},
          "after": {}
        }
      ]
    }
  ]
}
```

Порядок должен быть стабильным. Неизменённые элементы включаются явно.

## 11. Excel

Генератор не читает ORM лениво. Service заранее загружает данные и передаёт чистую
проекцию.

Ограничения Excel:

- безопасные имена листов и лимит 31 символ;
- уникализация одинаковых/длинных имён инженеров;
- стабильный порядок строк;
- время в московском часовом поясе;
- decimals без потери точности;
- отсутствие формул из пользовательских строк, способных вызвать formula injection;
- отсутствие диффа.

## 12. PDF/ZIP и S3

Настройки typed config:

- bucket/prefix exports;
- presigned URL TTL, целевое значение 15 минут;
- lifecycle retention, целевое значение 24 часа;
- максимальный размер экспорта;
- параметры PDF-рендера.

Lifecycle настраивается в S3/инфраструктуре; backend не создаёт фоновый cleanup. Ключи не
содержат адреса/имена и строятся из даты, типа экспорта и UUID.

## 13. Ошибки API

Нужны различимые доменные ошибки минимум для:

- approved initial already exists;
- current plan missing;
- plan not pending;
- initial expired;
- base plan changed;
- plan diverged from actual state;
- pending event already exists;
- invalid engineer availability transition;
- request already cancelled;
- urgent request already exists;
- plan belongs to another day;
- export generation failed;
- export storage unavailable.

Конфликты состояния используют 409. Ошибки формы — 422. Недоступность внешнего сервиса —
502. Router не ловит бизнес-исключения вручную.

## 14. Совместимость со старым Plans API

Сохраняются:

- request/engineer tiles;
- `planned_start` как главное время UI;
- фиксированный порядок групп заявок;
- карта и маршруты;
- plan-agnostic detail заявки/инженера;
- summaries отдельно от detail.

Заменяются:

- current «последний созданный» → последний approved за день;
- `manual_replan` → `replan`;
- `is_baseline` → отдельный `BaselineResult`;
- ID-only initial response → региональные summaries;
- отсутствующий lifecycle → pending/approved/rejected;
- отсутствие diff → вычисляемый вложенный diff;
- неопределённый partial success → явный результат по округам.

## 15. Проверки реализации

Помимо статических проверок нужны smoke/integration-сценарии:

1. несколько pending initial, approve одного;
2. проверка актуальности initial; для временного fallback — expiry через 10 минут;
3. replan от current и reject;
4. approve replan и автоматический reject siblings;
5. поздний approve с неизменённым прошлым;
6. поздний approve с изменением, ушедшим в прошлое;
7. атомарный rollback event replan;
8. invalid повторная недоступность/отмена;
9. доступен → недоступен → доступен → недоступен;
10. partial success нескольких округов;
11. diff со смешанными изменениями;
12. current на границе разных рабочих дней;
13. XLSX/PDF/ZIP и presigned URL;
14. параллельные approve одного округа.
