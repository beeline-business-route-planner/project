# ER-модель и нормализация

```text
scenarios 1 ── * datasets 1 ── * requests * ── 1 locations
    │              │                 │
    │              └── * import_errors
    │
    ├── * engineers * ── * skills
    │        └── * shifts
    ├── * day_events
    ├── * planning_runs 1 ── 1 plans ── * assignments ── 1 requests
    │                              ├── * unassigned_requests ── 1 requests
    │                              ├── * route_legs
    │                              ├── * plan_metrics
    │                              └── 0..1 plan_approvals
    └── * audit_log

requests 1 ── * request_status_events
```

`requests`, `engineers`, `shifts`, `assignments`, события и версии планов находятся в отдельных
таблицах. Справочные значения навыков, транспорта и видов работ не дублируются в строках заявок.
Повторяющийся адрес имеет одну строку `locations`, но каждая заявка сохраняет собственный ID.
Назначение не хранится в `requests`: оно принадлежит неизменяемой версии `plans`.

JSON применяется только для неизменяемого входного снимка алгоритма, диагностических данных,
payload события, геометрии и расширяемых метаданных. Эти поля не заменяют изменяемые связи.
Транзитивных зависимостей между бизнес-сущностями нет; повторяющиеся группы навыков вынесены в
`engineer_skills`. Частичная семантика «один активный утверждённый план» реализована nullable-полем
`approved_slot` и уникальным ограничением `(scenario_id, planning_date, approved_slot)`.

