# Реестр исправлений

Дата создания: 2026-09-18. Все задачи ниже — предложения по итогам [REPORT](REPORT.md), не выполненные исправления. При работе перепроверять актуальность находки. DONE требует фактической проверки.

Статусы: OPEN, NEEDS_DECISION, IN_PROGRESS, BLOCKED, DONE. Изменение приоритета/ownership записывать в журнал README.

## P0 — перед подключением replanning к backend

| ID | Задача | Владелец | Статус | Критерий завершения |
|---|---|---|---|---|
| P0-01 | Согласовать residual planner contract | Олег + Юрий; backend участвует | OPEN | Future-only; anchors≥T; preserved prefix; day-active IDs; complete/disjoint result; units/outcome/version описаны и проверены contract cases |
| P0-02 | Выбрать window policy и unavailable-current policy | TEAM_DECISION_REQUIRED | NEEDS_DECISION | Explicit START vs FINISH decision; текущая работа не завершена/переназначена молча; правило записано с provenance |
| P0-03 | ActualState(T) reader / demo input | Даниил, контракт Олега | OPEN | Статусы/времена/attribution/position/source age согласованы на T; unknown не заменяется офисом; historical import state учтён явно |
| P0-04 | Усилить independent validator | Юрий + backend; Олег residual invariants | IN_PROGRESS | Reject start<arrival, wrong destination, start<T, bad/missing matrix, assigned∩unassigned, changed preserved portion |
| P0-05 | Исправить unavailable + lock boundary | Олег + Юрий + backend | OPEN | A исключён только из future roster; preserved/current учтены вне solver; нет KeyError, zero unreachable или duplicate service |

Эти задачи не требуют предварительного большого refactor SqlGateway. Pure builder/tests возможны на explicit state; production integration ждёт P0.

Прогресс P0-04 от 2026-09-19: validator отклоняет `start < arrival`, неверный адрес заявки, пересечение assigned/unassigned, отсутствующую или повреждённую driving matrix, unreachable-дугу и изменение engineer/location/start/finish locked assignment. Добавлены regression cases; полный suite — 27 passed, Ruff и mypy(src) прошли. Проверка `start >= T` остаётся открытой до P0-03/P0-05: текущий snapshot пока содержит весь день и иначе будет отклонять собственный full-day candidate вместо фикса причины.

## P1 — до demo

| ID | Задача | Владелец | Статус | Критерий завершения |
|---|---|---|---|---|
| P1-01 | ReplanningService / ResidualProblemBuilder для unavailable | Олег | OPEN | A1/A2 immutable, A3/A4 residual, B/C actual anchors; новый draft не активируется автоматически |
| P1-02 | UUID события до outbox/audit | Даниил | DONE | Валидные ссылки, GET audit 200, regression test |
| P1-03 | Retry после неудачного event/run | Даниил; Олег orchestration | OPEN | Тот же idempotency key восстанавливает/возвращает результат, не duplicate-without-result; job/run state согласован |
| P1-04 | Actual timestamps / полный report | Даниил | OPEN | IN_PROGRESS(start)→COMPLETED(finish) сохраняет оба; unassigned/cancelled отражены отдельно; report freshness учитывает facts |
| P1-05 | Invalid input→422 | Даниил | DONE | Invalid planning_date/reversed window не дают 500; validation ctx безопасно сериализуется |
| P1-06 | Manual-change draft approval | Даниил | OPEN | Child initial draft имеет корректную base semantics; future edits не меняют completed/current |
| P1-07 | Combined work-type mapping | TEAM_DECISION_REQUIRED; Даниил реализует | NEEDS_DECISION | Утверждён норматив/skill для combined dataset rows; mapping tests |
| P1-08 | Реальный planner и transport profiles | Юрий + Даниил | OPEN | Adapter подключён; coverage→day-active objective; travel соответствует профилю; limitations явны |
| P1-09 | 2GIS длинная geometry / live scopes | Даниил | OPEN | Маршруты соблюдают points limit; реальные scopes проверены при ключе; partial provider errors диагностируются |
| P1-10 | Redaction key в HTTPX logs | Даниил | OPEN | Synthetic-key test не находит key в логах/ошибках |
| P1-11 | XLSX strings как текст | Даниил | OPEN | Untrusted identifiers/addresses не становятся formula |
| P1-12 | Валидация внешнего response | Даниил | OPEN | Negative/out-of-range indices, bad shape/WKT/JSON → controlled provider error, не corrupted matrix/500 |
| P1-13 | Day metrics и baseline | Олег semantics; Юрий objective; Даниил reporting | OPEN | Completed/current/future day-active union; eligible coverage без cancelled; сравнение на одинаковых inputs/matrices |
| P1-14 | Demo regression suite | Олег + Юрий + Даниил по слоям | OPEN | 12 event cases + anchors/time/partition/retry проходят; PostgreSQL flow подтверждён |

P1-02 завершён 2026-09-19: `DayEventRow` явно flush-ится до формирования outbox payload и audit row как для общего события, так и при создании новой заявки. HTTP regression подтверждает `GET /audit` 200 и совпадение audit object_id с event_id. Полный suite — 27 passed; Ruff/mypy(src) прошли.

P1-05 завершён 2026-09-19: query-параметры `planning_date` типизированы как date на FastAPI boundary; validation handler возвращает только сериализуемые type/loc/msg. Invalid date и reversed request window возвращают 422 с code=validation_error. Полный suite — 28 passed; Ruff/mypy(src) прошли.

## P2 — хорошо иметь

| ID | Задача | Владелец | Статус | Критерий завершения |
|---|---|---|---|---|
| P2-01 | ETA forecast + DeviationAnalyzer | Олег | OPEN | Без optimizer пересчитывает future ETA; small change не вызывает planner |
| P2-02 | Threshold/cooldown/hysteresis policy | Олег + команда | NEEDS_DECISION | Явные версии/пороги; no hidden urgency objective |
| P2-03 | TravelSnapshot provenance / cache | Даниил; требования Олега | OPEN | Logical/captured/departure times, profile/mode/hash/TTL; cache key корректный; outage не zero/demo fallback |
| P2-04 | Расширить PlanDiff | Даниил, semantics Олега | OPEN | Arrival/travel/reasons/future scope; не подменяет Actual deviation |
| P2-05 | Warm-start при измеримой пользе | Юрий | OPEN | Польза измерена; не required для корректности |
| P2-06 | Extract state reader из gateway | Даниил | OPEN | Policy не размножается в SQL; минимальный scope, existing flow проходит |
| P2-07 | Resource limits upload / локальное окружение | Даниил | OPEN | Multipart/expanded XLSX/rows bounded; compose exposure явен; install воспроизводим |

## P3 — после хакатона

| ID | Задача | Владелец | Статус | Критерий завершения |
|---|---|---|---|---|
| P3-01 | Реальные observations | Даниил; Олег state semantics | OPEN | Source/time/attribution доступны, stale handling проверен |
| P3-02 | Day revision / concurrency hardening | Даниил | OPEN | Approval/event/fact writers используют согласованный freshness protocol; PG race tests |
| P3-03 | Explicit migration evolution | Даниил | OPEN | Следующие schema changes — явные revisions; историческая migration не следует текущему Base |
| P3-04 | Recovery jobs / operational diagnostics | Даниил | OPEN | Failed/cancelled runs не зависают; resumable processing; no new framework без нужды |
| P3-05 | Дальнейшее разделение gateway | Даниил | OPEN | Выделяются конкретные bounded responsibilities без переписывания backend |

P3-02 — обнаруженный риск, не доказанная гонка. Если demo включает конкурентное редактирование, поднять приоритет до P1. P2-07 поднять до P1 при доступе недоверенных пользователей/публичном demo.

## Шаблон записи завершения

```text
ID:
Дата:
Причина и окончательное изменение:
Файлы:
Проверка (точная команда / case):
Результат:
Что не проверено:
Статус:
```

Команды downgrade выполнять только на новой disposable database. Не использовать ценную БД для audit rollback checks.
