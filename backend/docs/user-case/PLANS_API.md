# API чтения и представления планов

## 1. Назначение и статус

Документ задаёт подробный продуктовый контракт чтения плана: историю, current, полную
карточку, группировку заявок, маршруты инженеров и вычисляемый diff. Он входит в комплект
актуальных user cases и конкретизирует [`FULL_USER_CASE.md`](./FULL_USER_CASE.md),
[`BACKEND.md`](./BACKEND.md) и [`FRONTEND.md`](./FRONTEND.md), не меняя их смысл.

Это целевой контракт MVP. Фактический код может временно отставать от него в рамках
задач из `../tasks/` и не является основанием ослаблять описанное поведение.

## 2. Принципы чтения

1. План является неизменяемым снимком одного округа и рабочего дня.
2. История возвращает компактные summaries, а не маршруты и diff всех планов сразу.
3. Полная карточка загружается лениво по `plan_id` при открытии плана.
4. Генерационные endpoint возвращают региональные summaries/errors; detail читается
   отдельным запросом.
5. Current — последний `approved` по `approved_at DESC, id DESC` для пары
   `region + planning_date`.
6. `pending` и `rejected` никогда не подменяют current.
7. Initial не имеет diff. Для replan/event replan diff вычисляется относительно
   сохранённого `based_on_plan_id` и не хранится отдельной сущностью.
8. Baseline не является `Plan`, не попадает в историю и не имеет lifecycle.

## 3. Временная семантика остановки

Окно `Request.window_start/window_end` — обещанный клиенту интервал начала визита. Оно не
меняется при построении конкретного плана.

`PlanStop` замораживает рассчитанные значения:

| Поле | Значение |
|---|---|
| `planned_arrival` | Время физического прибытия инженера. |
| `planned_start` | Начало работы: не раньше `window_start`; при раннем прибытии инженер ждёт. |
| `planned_finish` | Завершение работы после полного норматива без дороги. |
| `travel_minutes` | Время пути к этой остановке. |
| `distance_km` | Длина соответствующего плеча маршрута. |

Основное время в UI — `planned_start`. `planned_arrival` необходимо для маршрута, аудита и
diff, но не подменяет обещанное время начала работы.

## 4. Summary плана

Summary используется в истории, региональных результатах initial/replan и ответах
approve/reject. Минимальный состав:

```text
id                         UUID
region                     enum
planning_date              date
kind                       initial | replan | event_replan
approval_status            pending | approved | rejected
created_at                 datetime
approved_at                datetime | null
rejected_at                datetime | null
approval_deadline          datetime | null
based_on_plan_id           UUID | null
triggered_by_event_id      UUID | null
is_current                 bool
assigned_requests_count    int
unassigned_requests_count  int
engineers_used_count       int
total_mileage_km           decimal
```

`based_on_plan_id` равен `null` только у initial. `triggered_by_event_id` заполнен только
у event replan. `is_current=true` допустим только для approved-плана.

История одного округа сортируется по `created_at DESC`, а при равенстве — по `id DESC`.
Статусы и виды отображаются всегда; дополнительные фильтры по ним необязательны для MVP.

## 5. Полная карточка

Полная карточка содержит:

- все поля summary;
- `calculation_cutoff_at`;
- агрегированные метрики загрузки;
- группы всех назначенных и неназначенных заявок;
- всех инженеров снимка плана, включая доступных без назначенных остановок;
- упорядоченные остановки каждого инженера;
- координаты, необходимые для карты;
- доступность approve/reject в текущем состоянии;
- `diff`: `null` у initial, вычисленный объект у replan/event replan.

Одна заявка встречается ровно один раз в общем представлении: либо среди назначенных,
либо среди неназначенных. Вложение той же назначенной заявки в маршрут инженера является
представлением связи, а не второй бизнес-записью.

## 6. Тайл заявки

Минимальный состав `RequestTile`:

```text
request_id           UUID
external_id          int
address              string
district             string
latitude             decimal
longitude            decimal
window_start         datetime
window_end           datetime
priority             int
required_skill       enum
planned_arrival      datetime | null
planned_start        datetime | null
planned_finish       datetime | null
travel_minutes       int | null
distance_km          decimal | null
sequence_number      int | null
is_locked            bool
assigned_engineer    {engineer_id, name} | null
unassigned_reason    enum | null
```

У назначенной заявки заполнены плановые времена, номер остановки и инженер, а
`unassigned_reason=null`. У неназначенной отсутствуют назначение и параметры остановки,
но обязательно заполнена причина неназначения.

Полная plan-agnostic карточка заявки читается через `GET /api/requests/{request_id}`.
Она не должна угадывать, относительно какого исторического плана пользователь открыл
заявку: контекст назначения уже содержится в тайле плана.

## 7. Группы заявок

Группы возвращаются в фиксированном порядке:

1. `emergency`;
2. `10-12`;
3. `12-14`;
4. `14-16`;
5. `16-18`;
6. `18-20`;
7. `20-22`;
8. `unassigned`.

Правила включения:

- любая неназначенная заявка попадает только в `unassigned`, включая аварийную;
- назначенная авария попадает в `emergency` независимо от времени;
- остальные назначенные заявки группируются по `planned_start`;
- назначенные внутри группы сортируются по `planned_start`, затем по адресу;
- неназначенные сортируются по адресу.

API возвращает стабильные ключи групп, а подписи и иконки локализует frontend.

## 8. Тайл инженера и маршрут

В `engineers` входят все инженеры снимка плана, в том числе без назначенных остановок.
У такого инженера `assigned_requests_count = 0` и `stops = []`; плановые показатели
передаются в том же формате. Фронтенд может показывать в списке маршрутов только
инженеров с остановками.
Минимальный состав `EngineerTile`:

```text
engineer_id               UUID
name                      string
vehicle_type              enum
shift_start               datetime
shift_end                 datetime
start_latitude            decimal
start_longitude           decimal
assigned_requests_count   int
route_distance_km         decimal
workload_without_travel   decimal
workload_with_travel      decimal
stops                     RequestTile[]
```

Инженеры сортируются по имени, остановки — по `sequence_number`. Маршрут начинается в
стартовой точке инженера и проходит через остановки в возвращённом порядке. Полная
plan-agnostic карточка инженера читается через `GET /api/engineers/{engineer_id}`.

Плановая загрузка считается относительно полной смены:

```text
workload_without_travel = sum(service_minutes) / shift_minutes * 100%
workload_with_travel =
    (sum(service_minutes) + sum(travel_minutes)) / shift_minutes * 100%
```

Ожидание открытия окна не входит ни в одну метрику. Эти показатели нельзя называть
фактической производительностью.

## 9. Вычисляемый diff

Для replan/event replan:

```text
before = based_on_plan_id
after  = открытый plan_id
```

Diff включает:

- `base_plan_id` и `candidate_plan_id`;
- before/after/delta для назначенных и неназначенных заявок, задействованных инженеров,
  общего пробега и загрузки;
- всех инженеров сравнения, включая неизменившихся;
- `before` и `after` по каждому инженеру;
- все заявки инженера и набор изменений каждой заявки.

Изменение инженера: `added`, `removed`, `changed`, `unchanged`.

Изменения заявки не взаимоисключающие:

- `added`;
- `removed`;
- `reassigned`;
- `reordered`;
- `rescheduled`;
- `travel_changed`;
- `assignment_changed`;
- `unassigned_reason_changed`;
- `unchanged`.

Для добавленного элемента `before=null`, для удалённого `after=null`. При изменении API
возвращает старые и новые значения времени прибытия, начала и завершения, дороги,
километража, порядка, назначения и причины неназначения. Frontend отображает готовый diff
и не повторяет бизнес-сравнение самостоятельно.

## 10. HTTP API

### `GET /api/plans/current`

Query:

- `region` — обязательный;
- `planning_date` — опциональный, по умолчанию текущая дата Москвы.

Возвращает полную карточку только current approved-плана. Если approved-плана за дату нет,
возвращается доменное пустое состояние/ошибка отсутствия current; pending не используется
как fallback.

### `GET /api/plans?region=...`

Возвращает summaries всех планов выбранного округа и всех статусов, новые сверху. В MVP
обязателен только фильтр округа.

### `GET /api/plans/{plan_id}`

Возвращает полную карточку любого доступного плана: pending, rejected, current или
исторического approved. Для replan/event replan в этот же ответ включается diff; отдельный
endpoint diff в MVP не нужен.

### `POST /api/plans/{plan_id}/approve`

Разрешён только для применимого pending-плана. Тело отсутствует. Возвращает обновлённый
summary/current metadata; полный detail при необходимости перечитывается отдельным GET.
Повторный approve и approve rejected/устаревшего кандидата завершаются конфликтом.

### `POST /api/plans/{plan_id}/reject`

Разрешён только для pending-плана. Тело и причина отсутствуют. Рабочий current не меняется.

### `GET /api/plans/{plan_id}/export`

Доступен для любого статуса плана. Генерирует XLSX, сохраняет его в S3 и возвращает
временную ссылку с моментом истечения. Экспорт не меняет lifecycle плана.

## 11. Ленивый пользовательский поток

1. Initial/replan/event replan возвращает summary или региональную ошибку.
2. Frontend создаёт вкладки успешных округов без загрузки всех маршрутов.
3. При открытии вкладки вызывается `GET /api/plans/{plan_id}`.
4. Detail возвращает полный план, актуальный lifecycle, доступность действий и diff.
5. После approve/reject frontend перечитывает history и при необходимости current.

Главный экран всегда читает `GET /api/plans/current` и поэтому показывает только рабочий
approved-план выбранного округа и дня.

## 12. Правила карты

- По умолчанию показываются точки всех заявок без одновременного отображения всех маршрутов.
- Выбор назначенной заявки показывает маршрут её инженера.
- Выбор инженера показывает только его маршрут.
- Маршруты остальных инженеров серым фоном не рисуются.
- Неназначенная заявка остаётся видимой как точка, но не имеет маршрута.
- Кластеризация близких точек выполняется frontend.
- Для diff минимальный MVP показывает новый план и подсветку изменённых точек; два полных
  слоя старых и новых маршрутов без управления слоями не накладываются.

## 13. Инварианты ответа

- current всегда approved и относится к запрошенным `region + planning_date`;
- `is_current` не вычисляется только по `created_at`;
- initial имеет `based_on_plan_id=null` и `diff=null`;
- replan/event replan имеют неизменную базу diff;
- `is_baseline` отсутствует;
- counts соответствуют фактическому содержимому карточки;
- каждая заявка представлена как assigned xor unassigned;
- `sequence_number` уникален и непрерывен внутри маршрута инженера;
- `planned_start >= planned_arrival` и `planned_finish >= planned_start`;
- история и detail не скрывают pending/rejected планы;
- pending/rejected не влияют на главный экран и дневные отчёты.
