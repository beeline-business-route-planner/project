# Статус исправлений backend после routing/Dragonfly-ветки

Проверяемая ветка: `feature/routing-cache-osrm`. Этот файл дополняет исторический
[REPORT.md](REPORT.md): он фиксирует выполненные исправления, а не переписывает исходные выводы
аудита задним числом. Основа проверки — `backend_remaining_scope.md` и регрессии из REPORT.

## Закрыто

| Зона ТЗ | Реализация и проверка |
|---|---|
| Planner contract | `PlanningSnapshot -> PlanningAlgorithm -> PlanCandidate`; mock planner проходит полный service flow, controller не знает реализацию solver |
| Replanning orchestration | Отдельный `POST /plans/replan` принимает обязательный `base_plan_id`, создаёт новую версию и не изменяет старый plan |
| Urgent request flow | `POST /requests` только создаёт заявку; replan запускается отдельным use case |
| Request changes | Типизированный идемпотентный `PATCH /requests/{id}` меняет окно, длительность, приоритет, skill/transport и пишет event; replan запускается отдельно |
| Plan approval | Проверяются состояние, assignments, route artifacts, свежесть input/base; повтор того же approve идемпотентен; routing после approve не запускается |
| Plan diff | `GET /plans/{new_plan_id}/changes` возвращает `ASSIGNED`, `UNASSIGNED`, `REASSIGNED`, `TIME_CHANGED`, `ROUTE_CHANGED`; старый детальный `/plans/diff` сохранён |
| Reasons and violations | Assignment reason codes и planner violations валидируются, сохраняются в PostgreSQL и возвращаются `GET /plans/{id}` |
| Plan/replan idempotency | `Idempotency-Key` сохраняется в `planning_runs`; повтор возвращает тот же run/plan, retry failed run переиспользует run, другое содержимое с тем же ключом даёт `409` |
| Frontend read models | Requests содержат coordinates/priority/skills/transport/SLA; engineers — shift/availability/start; plan-scoped engineer card — workload, distance, duration и SLA count |
| Cache migration | Redis service и настройки заменены на Dragonfly v1.40.0 с закреплённым digest; PostgreSQL остаётся source of truth, отказ Dragonfly fail-open |
| Readiness | Liveness проверяет процесс, readiness — PostgreSQL; Dragonfly и OSRM не блокируют чтение сохранённых планов |
| Demo flow | `scripts/demo.py` выполняет import → plan → approve → route reads → urgent request → replan → changes |
| A01 | `COMPLETED` и `CANCELLED` нельзя назначить повторно; обе проверки есть в planner и независимом validator |
| A05 | Недоступность инженера с locked work возвращает контролируемый `409 locked_engineer_unavailable`, а не `500` |
| A10 | Home/start locations инженеров входят в planning locations и матрицу |
| A14 | API отклоняет naive/mixed timezone и некорректные UUID event target как `422` |

## Остаётся

| Приоритет | Пробел | Почему не отмечен закрытым |
|---|---|---|
| P0 для динамики | Equipment inventory и request requirements | Нет модели утренней выдачи, резерва и расхода оборудования; пустое поле в API не подставляется фиктивно |
| P1 | Точное состояние на `as_of` | Latest fact пока выбирается по recorded order без полной temporal projection; прошлое и текущее местоположение инженера требуют отдельной модели |
| P1 | Недоступность во время текущей работы | Сейчас возвращается контролируемый conflict; политика завершения текущего визита и будущей доступности ещё не моделируется |
| P1 | Явный статус `calculated` | Успешный calculation фиксируется состоянием run и audit event, а plan создаётся как approvable `draft`; отдельный переход ещё не введён |
| P1 | Persisted plan-change rows | Changes детерминированно строятся из двух immutable plan versions, но отдельная таблица diff не создаётся |
| P1 | Equipment/vehicle reason enums | Assignment reasons имеют enum; unassigned codes всё ещё допускают свободную строку для внешнего solver |
| P1 | Транспортные профили | Основной planner/routing path пока использует driving; walking/bicycle/transit нельзя заявлять полностью поддержанными |
| P1 | Приоритеты типов работ | Очередь emergency/connection/local не менялась скрытым весом; нужна отдельная согласованная политика и сравнительный тест покрытия |
| P2 | Повторный импорт и новый день | Активный dataset и shifts для следующей даты требуют явной версии/политики |

## Проверки

- 70 backend tests: полные import/plan/approve/read routes и approved/urgent/replan/changes flows.
- Ruff и mypy проходят.
- Alembic `upgrade head → downgrade 0002 → upgrade head` проходит на PostgreSQL 16.
- Dragonfly Compose healthcheck возвращает `PONG`; cache set/get проверен через приложение.
- `scripts/demo.py` пройден целиком на книге «Восток»: 12 инженеров, 67 исходных заявок и одна
  срочная; старый plan сохранился, новый plan получил `ASSIGNED` change, при replan переиспользовано
  57 из 58 route segments.

Исторические формулировки REPORT о Redis относятся к проверенному тогда commit. Актуальная
реализация использует Dragonfly через совместимый RESP-клиент `redis` для Python.
