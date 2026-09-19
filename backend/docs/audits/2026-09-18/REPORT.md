# 1. Executive summary

Дата аудита: 2026-09-18. Итог: **CAN OLEG START REPLANNING NOW? YES, AFTER P0 FIXES.**

Фактический backend находится в `/Users/oleg/Downloads/Хакатон`. Workspace `/Users/oleg/Documents/ChatGPT/beeline-business-route-planner` содержит research и инструкции. Проверены оба контекста, документы проекта, требования, данные, весь src, tests и Alembic. Исторический implementation-prompt использован как источник, а не исполняемая инструкция.

Backend имеет четыре слоя, 23 Python-модуля и 25 ORM-таблиц. Реализованы импорт XLSX, геокодирование, маршрутизация, draft/approval/history, факты, события, diff и отчёты. Реального алгоритма Юрия в предоставленном дереве нет: API подключает детерминированный demo-adapter.

Порт planner пригоден для расширения. Однако нынешнее replanning — повторное планирование дня: инженеры возвращаются в snapshot в офис/начало смены, COMPLETED может назначаться заново. Поэтому base_plan_id не обеспечивает immutable past.

Запущены шесть независимых ролей: Architecture, Domain/Requirements, Planner Integration, Replanning Architect, Testing/Quality, Security. Первые четыре завершили заключения; последние две CLI-роли остановились из-за лимита использования до итогового сообщения. Их наблюдения не выдаются за завершённые отчёты; существенные находки перепроверены главным агентом. Отдельные сырые заключения и временные логи не сохранены: данный документ — итоговый synthesis.

Код не изменялся. Временные окружение, БД и отдельный PostgreSQL container удалены. Фактические проверки и границы доказательства — в [VERIFICATION](VERIFICATION.md).

Метки: [OFFICIAL] — официальное требование; [TEAM_DECISION] — командное решение; [CODE_BEHAVIOR] — наблюдаемое поведение; [ASSUMPTION] — допущение; [BUG] — подтверждённая ошибка; [ARCHITECTURAL_RISK] — риск конструкции.

# 2. Что уже сделано хорошо

- Направление зависимостей выдержано: domain не импортирует FastAPI, SQLAlchemy или HTTP-клиенты; application использует порты. Python dependency cycles не обнаружены.
- [PlanningAlgorithm.plan](/Users/oleg/Downloads/Хакатон/src/beeline_backend/application/ports.py:45) принимает snapshot и возвращает PlanCandidate, не зависит от SQL/HTTP.
- [EngineerData](/Users/oleg/Downloads/Хакатон/src/beeline_backend/application/contracts.py:34) уже содержит available_from и available_location_id.
- Service и travel разделены; нормативная дорога не должна считаться повторно. Матрицы направленные, секунды/метры, unreachable=None.
- Есть независимый [validate_candidate](/Users/oleg/Downloads/Хакатон/src/beeline_backend/application/planner.py:156).
- Есть сохранённые input snapshots, runs, draft/approved/superseded, base plan и история назначений.
- [approve_plan](/Users/oleg/Downloads/Хакатон/src/beeline_backend/infrastructure/gateway.py:956) использует блокировки и ограничения уникальности активного плана.
- Providers вынесены в адаптеры и имеют mock contract tests.
- Реальный основной HTTP-flow и миграции на отдельном PostgreSQL успешно выполнены.

# 3. Critical problems

| Находка | Evidence | Impact |
|---|---|---|
| [BUG] Snapshot не задаёт остаток дня | gateway.build_snapshot:619/680; as_of=13:00 дал назначение 08:10, принятое validator | Повторно планируется утро |
| [BUG] COMPLETED обрабатывается как FUTURE | planner.plan:60; повторное назначение воспроизведено | Прошлое изменяемо |
| [BUG] Unavailable + current lock | planner.py:38; исключён engineer, сохранён lock, KeyError | Event committed, HTTP 500 |
| [BUG] Слабый validator | planner.validate_candidate:156 | Приняты start<arrival, assigned∩unassigned, изменённое время lock |
| [BUG] Retry не восстанавливает ошибку | services.create_event_and_replan:132 | Duplicate=True, replanning=None после неудачи |
| [BUG] UUID используется до flush | gateway.create_event:1295/1310/1320 | Outbox event_id="None", audit object_id="None", GET audit 500 |
| [ARCHITECTURAL_RISK] Нет ActualState(T) | _latest_statuses:381, build_snapshot | Последний recorded status не обязательно состояние на T; нет достоверных anchors |
| [BUG] Report теряет actual_start | record_fact:1159, report_payload:1528 | IN_PROGRESS(start) → COMPLETED(finish) даёт actual_start=None |

Additional confirmed failures: неверная planning_date даёт 500; перевёрнутое окно даёт 500 из-за несериализуемого ValueError в validation ctx; child draft после manual-change исходного draft не утверждается из-за stale_base_plan.

# 4. Requirements drift

Source priority: Q&A → официальное ТЗ → dataset/normative → архитектурные решения → актуальный командный план → docs → code. [Source manifest](/Users/oleg/Documents/ChatGPT/beeline-business-route-planner/_bmad-output/research/source-manifest.md).

[OFFICIAL] Q&A: больше выполненных заявок, затем меньше задействованных инженеров. [Transcript](/Users/oleg/Downloads/tg/transcript_clean.txt:188), таймкод около 00:33:38. Пробег — метрика/последующий критерий, не скрытый вес против coverage.

[OFFICIAL] Q&A: начало работ внутри клиентского окна, завершение до конца смены; не требуется завершение внутри клиентского окна. [Transcript](/Users/oleg/Downloads/tg/transcript_clean.txt:260), около 00:44:03. Официальное [ТЗ](/Users/oleg/Downloads/Хакатон/3.%20Билайн%20Бизнес.pdf), страницы 3–5, 7–8.

[TEAM_DECISION] [Integration decisions](/Users/oleg/Downloads/Хакатон/beeline-integration-decisions.md:19) явно требует завершать внутри окна и признаёт более строгое правило. Это не случайный bug. Но с текущим приоритетом официальных источников требуется явное пересогласование, а не молчаливое изменение.

| REQUIREMENT / DECISION | EXPECTED | ACTUAL | STATUS | EVIDENCE | ACTION |
|---|---|---|---|---|---|
| Dispatcher backend | Заявки/план/утверждение/история | Основные операции есть | Соответствует | api.py | Переиспользовать |
| Requests | Типы/окна/координаты/статус | Есть, combined mapping неоднозначен | Частично | importer._classify | Согласовать mapping |
| Engineers | Skills/transport/region/shift | Есть; synthetic 12 car engineers | ASSUMPTION | _seed_engineers | Маркировать synthetic |
| Plans/history | Независимые версии | Есть lifecycle/base/snapshot | Частично | models/approve_plan | Усилить freshness |
| Plan generation | Алгоритм Юрия через порт | Demo-adapter | Не завершено | api._provider_bundle:123 | Подключить реальный planner |
| Approval | Stale draft не активируется | Основная защита есть | Частично | approve_plan | Day revision |
| Unique assignment | Максимум один исполнитель | ORM/validator проверяют назначения | Частично | models/planner | Также disjoint assigned/unassigned |
| Skills | Требуемый skill | Проверяется | Соответствует | planner | Сохранить |
| Transport | Допуск + соответствующий travel | Допуск есть, travel driving | Частично | services.run_plan | Явные profiles |
| Region | Допустимый регион | Преимущественно scenario boundary | Частично | build_snapshot | Явная проверка |
| Reachability | Unreachable запрещает дугу | В locked path None→0 | BUG | planner.plan | Убрать подмену |
| Time window | Start внутри окна | Также finish внутри | TEAM_DECISION / drift | calculate_visit/decisions | Решение команды |
| Shift | Finish до конца смены | Проверяется | Соответствует | validator | Сохранить |
| Service/travel | Не считать дорогу дважды | Разделены | Соответствует | importer/normative | Сохранить |
| Coverage first | Max serviced | Demo не гарантирует | Не доказано | planner | Юрий: objective |
| Active engineers | Min после coverage | Demo может задействовать 2 вместо 1 | Drift | planner | Lexicographic objective |
| Day metrics | Полный день после replan | Только candidate | Частично | save_candidate | Day/residual отдельно |
| Mileage | Distance + одинаковый baseline | Distance есть, полного comparison нет | Частично | metrics/reports | Baseline comparison |
| Unassigned reasons | Корректная диагностика | Есть; агрегация причин неверна в отдельных случаях | Частично | planner | Негативные tests |
| Event model | Typed event + effective time | Envelope + общий dict | Частично | dto/create_event | Typed payload |
| Regeneration | Только будущее | Весь день заново | BUG | build_snapshot/run_plan | Residual builder |
| Status update | Состояние на T + история | Latest recorded | Частично | _latest_statuses | State reader |
| Reports | Полные заявки/факты | Только assignments, actual_start теряется | BUG/частично | report_payload | Агрегирование фактов |
| Routing/geocoding | Рабочие проверенные providers | 2GIS код есть, Yandex placeholder | Частично | providers | Live 2GIS |
| Comparison | Plan diff и Actual deviation | Только assignment diff | Частично | diff_plans | DeviationAnalyzer |
| Planner/backend separation | Solver независим, policy в application | Port независим; policy в SQL gateway | Частично | ports/gateway | Новая логика вне SQL |
| DB schema | Эволюционируемая схема | Initial migration использует текущий Base | Риск | 0001_initial | Explicit migrations |
| Testability | Negative contract tests | Хорошая основа, пробелы инвариантов | Частично | tests | Adversarial tests |
| Actual positions | Продолжить из actual | Офис | Отсутствует | build_snapshot | EngineerState/anchors |
| Traffic trigger | Refresh→forecast→decision | Нет | Отсутствует | services | DeviationAnalyzer |

Combined mapping: `_classify('Подключение', 'Заказ подключения/Дозаказ оборудования')` выбирает equipment_order с service 20/full 40. Подобные строки реально есть в dataset. Корректный норматив для объединённого случая не утверждён; поведение нельзя считать правильным по одному коду.

# 5. Architecture review

```text
FastAPI / DTO → BackendService
                 → Gateway port → SqlGateway → SQLAlchemy / DB
                 → Geocoder / RoutingProvider
                 → PlanningAlgorithm → independent validator
                 → geometry / сохранение draft / metrics
```

Формальные слои выдержаны. SqlGateway (~1600 строк) — god object: кроме persistence управляет snapshot policy, locks, availability, manual schedule, metrics/report state. BackendService объединяет use cases, а промежуточные commits оставляют частично завершённый event/run workflow. app.state — композиция на API-границе, не domain service locator. ORM не передаётся solver; FastAPI не протекает в domain/application. FK-cycle runs/plans не равен Python dependency cycle.

| Область | STATUS | EVIDENCE | IMPACT | Минимальное исправление |
|---|---|---|---|---|
| Architecture | ACCEPTABLE | Слои/ports | Расширение возможно | Сохранить направления |
| Domain | NEEDS_WORK | Status/locks | Нет past/current/future boundary | Phase отдельно от deviation |
| Application | NEEDS_WORK | BackendService | Partial success | ReplanningService |
| Infrastructure | NEEDS_WORK | SqlGateway | Policy связана с SQL | Residual logic в application |
| API | NEEDS_WORK | Dates/payload | Invalid input→500 | Typed validation |
| Database | ACCEPTABLE | Constraints/history | Lifecycle работает | Day revision/state fields |
| Testing | NEEDS_WORK | 24 passing | Инварианты пропущены | Negative tests |
| Documentation | NEEDS_WORK | Старые роли/стабильность snapshot | Неясные гарантии | Actual ownership/limits |
| Error handling | NEEDS_WORK | Retry/parsing | Нет recovery | Run/job outcome |
| Integrations | NEEDS_WORK | 2GIS/Yandex | Default не проверен live | Scopes/route limits |
| Maintainability | NEEDS_WORK | Gateway/manual schedule | Дублирование политики | Общий residual flow |
| Replanning extension | NEEDS_WORK | Anchors есть, reader нет | Вход неверен | P0 contracts |
| Security | NEEDS_WORK | Logs/Excel | Key leak/formula | Redaction/text export |
| Hackathon readiness | NEEDS_WORK | Happy path проходит | Unavailable mid-day ломается | P0/P1 |

# 6. Planner contract review

**NEEDS CONTRACT CHANGE.** Сигнатуру `plan(snapshot) -> PlanCandidate` можно сохранить.

| Capability | Сейчас |
|---|---|
| Нет SQL/HTTP | Да |
| Current time | as_of есть, future boundary не обеспечен |
| Current positions | Поле есть, gateway задаёт офис |
| Subset requests | Технически да |
| Exclude engineer | Да, но conflicts с locks |
| Remaining shift | Через availability/shift end |
| Warm-start | Отдельного контракта нет |
| Reasons | Есть, неполная корректность |
| Metrics | Основные считает backend |
| Determinism | Demo да; Юрий не проверен |
| Timeout/outcome | Нет explicit optimal/feasible/timeout result |
| Input immutability | Frozen поверхностный; nested lists/DTO изменяемы |

Согласовать: future-only pool; ready time≥T; actual/next-available point в matrix; preserved past снаружи solver; day-active engineer IDs; complete/disjoint assigned/unassigned; profile/shape validation; explicit outcome и algorithm version. Warm-start не является обязательным P0.

Validator: start≥arrival; destination=request location; start≥T/ready; полная правильная матрица; assigned∩unassigned=∅; preserved portion immutable. Нельзя валидировать прошлое по новой дорожной ситуации и объявлять историческое нарушение недопустимостью будущего плана.

# 7. Replanning readiness

Reuse: PlanningAlgorithm, snapshot/data DTO, PlanCandidate, RoutingProvider, TravelSnapshot, clock, draft/approval/history, существующий plan diff.

Missing: ActualState(T), preserved prefix, residual builder, next-available anchors, unavailable-current policy, Plan vs Actual analyzer, day metrics/freshness revision.

Олег не переписывает optimizer, SQL CRUD, importer, reporting или Alembic. Contracts согласуются совместно. Для pure builder новая БД не нужна. Для интеграции backend должен хранить/читать attribution текущей работы, observation point/time/source и expected availability. В demo допустим явный ручной state.

Existing event/fact API можно сохранить с typed payload и временной семантикой. Urgent request added и повышение urgency существующей request — разные операции. OVERDUE должен быть deviation flag, не потерей IN_PROGRESS/EN_ROUTE.

# 8. Proposed replanning architecture

```text
PreviousApprovedPlan + ActualState(T) + Event
    → ResidualProblemBuilder → residual snapshot + travel
    → тот же PlanningAlgorithm → residual validator
    → preserved portion + residual result → composition validator
    → новый DRAFT + PlanDiff
```

ReplanningService, ResidualProblemBuilder и DeviationAnalyzer живут в application. Маленькие event/state/policy value objects — domain/contracts. SQL reader/persistence — infrastructure через ports. Второй backend не нужен.

- COMPLETED сохраняются вне solver, actual timestamps отдельно.
- IN_PROGRESS/EN_ROUTE сохраняют исполнителя и текущее обязательство; future anchor после ожидаемого освобождения.
- FUTURE включает прежние неназначенные и новые заявки.
- CANCELLED исключаются из обслуживания, остаются в истории.

Current work лучше учитывать через anchor и preserved portion, а не повторно обслуживать как locked request.

A/B/C в 13:00: A1/A2 immutable; A3/A4 в future pool; A исключён только из future roster, остаётся в day history/metrics; B стартует из actual point≥13:00; занятый C — из next-available point/time, например 13:25. Невместившиеся остаются unassigned.

TEAM_DECISION_REQUIRED: unavailable во время текущего исполнения. Минимальная предлагаемая policy MANUAL_REVIEW, без автоматического завершения/переназначения/продолжения. Unknown state→NEED_ACTUAL_STATE, не office fallback.

Day active count = unique(completed ∪ current ∪ future engineers). Residual count хранить отдельно. Cancelled не должен ухудшать eligible coverage.

# 9. Plan vs Actual / Traffic design

```text
ApprovedPlan + ActualState(T) + CurrentTravel
    → ETA forecast в существующем порядке, без оптимизации
    → DeviationAnalyzer → ReplanningPolicy
    → KEEP / REFRESH_ETA / REPLAN / NEED_ACTUAL_STATE
```

Реально доступны статусы, вручную введённые timestamps, назначения и адресные coordinates. Полноценного GPS feed нет. Demo state маркировать simulated/demo_manual с observation time/source.

2GIS matrix код использует type=jam. [Официальные примеры](https://docs.2gis.com/en/api/navigation/distance-matrix/examples) различают текущие пробки и statistics/start_time для прогноза; start_time сам по себе не доказывает future traffic. OSRM adapter игнорирует departure_at. Yandex placeholder. Live 2GIS не проверен: ключ отсутствует.

Geometry отправляет весь маршрут одним запросом. [Официальный Routing overview](https://docs.2gis.com/en/api/navigation/routing/overview): car максимум 10 точек, walking 5. Нужен split длинных маршрутов. Distance matrix блоки 25 источников/25 целей реализованы отдельно; это не снимает routing limit.

TravelSnapshot: различать logical T, captured_at, departure_at, profile, provider/version, traffic mode, coordinate/matrix hash, validity. Для августовского scenario нельзя выдавать текущие сентябрьские пробки за исторические. Demo: reproducible simulated snapshots/seed либо явное согласованное отображение даты.

Кеш: существующий PostgreSQL RouteCache + per-run memory; сейчас полноценный read-through не подключён. Directed pair + coordinate versions + provider + profile + traffic mode + departure bucket/config в ключе.

Outage: сохранять approved plan, показывать stale forecast; last valid travel только по explicit TTL. Не подменять zero travel/demo и не считать outage доказательством unreachable.

Fresh hard violation→REPLAN; малое ETA change→REFRESH_ETA; unknown state→NEED_ACTUAL_STATE. Delay threshold, cooldown/hysteresis — TEAM_DECISION_REQUIRED. Пример 15 минут — ASSUMPTION, не official rule. Periodic refresh не означает periodic full optimization. Cron сейчас не создавался.

# 10. Ownership

| TASK | OLEG | YURIY | DANIIL/BACKEND | FRONTEND |
|---|---|---|---|---|
| Residual builder | Основной | Input contract | State reader | — |
| ReplanningService | Основной | Planner port | Persistence/wiring | — |
| Preserved prefix/anchors | Логика | Contract support | Data load | — |
| Initial optimization | — | Основной | Wiring | — |
| Timeout/outcome | Consumer | Основной | Persistence | — |
| Independent validation | Residual/composition | Solver contract | General validator совместно | — |
| Unavailable current work | TEAM_DECISION_REQUIRED | Участие | Участие | — |
| ActualState(T) | Контракт | — | Основной | Вне задачи |
| Typed API | Семантика | — | Основной | Вне задачи |
| Retry/UUID/jobs/audit | — | — | Основной | — |
| Day revision/approval | Требования | — | Основной | — |
| ETA/deviation | Основной | — | Provider access | — |
| Traffic policy | Основной, team decision | Участие | Участие | — |
| Profiles/cache | Требования | Usage | Основной | — |
| Reports/day metrics | Семантика | Objective | Основной | — |
| Replanning tests | Основной | Contract tests | API/DB tests | — |

# 11. Tests

24 pytest passed, 2 deprecation warnings; Ruff passed; mypy passed (23 files); SQLite/PostgreSQL migrations and PostgreSQL main flow passed; real uvicorn health/readiness/docs/openapi 200 с demo providers. Live OSRM/Nominatim minimal calls passed. Подробности и limitations в VERIFICATION. Процент coverage не измерялся.

Будущие минимальные cases: unavailable before first; unavailable after completed; unavailable while current; successful redistribution; partial redistribution; skills; transport; window/shift; urgent added; cancellation; traffic ETA risk; small traffic change→no planner call.

Также: actual B/C anchors; future not before T; previous unassigned included; stale observations; day-active count preserved; failed event retry; candidate partition; locked/preserved invariance; input mutation; report timestamps; malformed provider/API response; concurrency on separate PG.

# 12. Security

- [BUG] 2GIS key в query URL попадает в HTTPX INFO log. Подтверждено synthetic key/mock, без реального секрета. Redaction/filter; providers.py:343 и logging setup.
- [BUG] XLSX formula injection: external_id `=1+1` записывается как formula (data_type=f). Text export; reports.py:47. Опасные формулы не выполнялись.
- [ARCHITECTURAL_RISK] Upload cap после multipart parsing; нет expanded XLSX/row cap. api.py:257/importer.py:68. DoS/ZIP-bomb не проводился.
- [BUG] Provider response: negative source_id принят как последний index; array JSON даёт AttributeError. Validate shape/types/index ranges.
- [BUG] Invalid date/window→500; ctx ValueError не JSON-serializable. Typed input/safe error serialization.
- [ARCHITECTURAL_RISK] Approval/fact writers не разделяют общую day revision/lock. Статический риск, concurrent proof не выполнен.
- [CODE_BEHAVIOR] Compose ports без localhost restriction, image root, install не frozen uv.lock. Уточнить окружение/границы доступа и reproducibility.

Secrets не выводились; реальный API key в проверенной конфигурации не найден. .env исключён из Git/build. SQL injection/path traversal не подтверждены. CVE scan не запускался. Auth исключена из обязательного official MVP, её отсутствие само по себе не баг этого scope.

# 13. Minimal refactor plan

P0: residual contract; спорные policies; ActualState(T); independent validator; unavailable/locks boundary. Не требуется переписывать весь gateway.

P1: unavailable flow; UUID/audit/retry; reports; invalid input; manual draft approval; combined mapping; real planner/profiles; geometry split; key redaction/formula protection; regression tests/baseline.

P2: ETA/deviation; cache; richer diff; полезный warm-start; небольшое извлечение reader/persistence.

P3: real observations; concurrency/recovery hardening; дальнейшая декомпозиция gateway; operational diagnostics.

Постоянные ID, критерии завершения и статусы — [FIX_PLAN](FIX_PLAN.md). Kafka/Kubernetes/CQRS/event sourcing/workflow engine не нужны.

# 14. Files to change

Предложения, файлы реализации пока не созданы:

- Новый `/Users/oleg/Downloads/Хакатон/src/beeline_backend/application/replanning.py`: builder/service/composition checks.
- Новый `/Users/oleg/Downloads/Хакатон/src/beeline_backend/application/deviation.py`: forecast/analyzer/policy.
- [contracts.py](/Users/oleg/Downloads/Хакатон/src/beeline_backend/application/contracts.py): state/anchors/context, совместно.
- [ports.py](/Users/oleg/Downloads/Хакатон/src/beeline_backend/application/ports.py): reader/traffic contracts, сохранить planner port.
- [domain/model.py](/Users/oleg/Downloads/Хакатон/src/beeline_backend/domain/model.py): только необходимые value objects.
- [services.py](/Users/oleg/Downloads/Хакатон/src/beeline_backend/application/services.py): делегирование, совместно с backend.
- Новые tests/test_replanning.py и tests/test_deviation.py; совместные tests/test_planner_contract.py.

Gateway/models/API/DTO/providers/reports/Alembic — преимущественно Даниил. Algorithm и его contract semantics — Юрий.

# 15. Final checkpoint

**YES, AFTER P0 FIXES.** Порт, snapshot, availability и plan lifecycle подходят. Но backend пока не гарантирует immutable past и actual continuation.

Pure builder prototype/tests на явно заданном state можно начинать. Интеграция требует согласованного residual contract, достоверных anchors, политики текущей работы и усиленного validator.

Исходный аудит завершён без изменения кода. Последующая просьба пользователя разрешила сохранить документацию; реализация исправлений на этом этапе не начата.
