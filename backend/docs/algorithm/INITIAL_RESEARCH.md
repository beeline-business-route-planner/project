# Initial: фактическое состояние и исследовательские замеры

## Статус документа

Документ фиксирует фактическое состояние реализации initial в `src/core/algorithm/` и
результаты замеров на 24 сентября 2026 года. Нормативный контракт алгоритма остаётся в
[`../user-case/ALGORITHM.md`](../user-case/ALGORITHM.md), рабочая спецификация обсуждения —
в [`README.md`](./README.md). Здесь только то, что реально реализовано и измерено, плюс
гипотезы следующего шага.

**Граница ответственности.** Алгоритмическая дорожка следует задачам `A00–A02`: алгоритм —
чистое вычислительное ядро без БД, routing I/O, часов и commit; загрузку данных, запрос
матриц, сохранение `Plan`/`BaselineResult` и lifecycle выполняет API-domain orchestration.
Вариант «алгоритм сам читает БД и сохраняет план» из раздела 2.1 рабочей спецификации в
текущей реализации не используется.

## 1. Реализованный конвейер initial

```text
PlanningService (orchestration, временный adapter до T03/G02)
  ├─ загрузка Request/Engineer одного upload, сортировка по UUIDv7
  ├─ calculation_cutoff_at = now(Europe/Moscow), один раз на округ
  ├─ AlgorithmService.prepare_initial(InitialPlanningSnapshot) → InitialPlanningDraft
  │    InitialInputNormalizer:
  │      авария → release 10:00, latest_start 12:00; available_from = max(смена, cutoff)
  │      группировка по эффективному окну → слои
  │      LayerMatrixRequest на слой × тип транспорта (traffic_reference_at = середина окна)
  │        sources = старты инженеров транспорта + заявки текущего и предыдущих слоёв
  │        targets = заявки текущего слоя, доступные этому транспорту
  ├─ 2ГИС Distance Matrix на каждый LayerMatrixRequest → LayerMatrix
  ├─ AlgorithmService.build_initial_input(draft, matrices) → InitialPlanningInput
  ├─ AlgorithmService.plan_initial(input) → InitialPlanningResult
  │     ├─ LayeredGraphPlanner.assign        распределение и порядок
  │     ├─ ScheduleMaterializer             arrival/start/finish слева направо
  │     ├─ классификация unassigned
  │     ├─ метрики
  │     └─ ResultAuditor                    независимый аудит
  ├─ AlgorithmService.plan_baseline(input) → метрики baseline
  └─ одна транзакция: pending Plan + stops + unassigned + BaselineResult
```

Файлы ядра:

| Файл | Ответственность |
|---|---|
| `service.py` | `AlgorithmService`: `prepare_initial`, `build_initial_input`, `plan_initial`, `plan_baseline`, `plan_initial_diagnosed` |
| `normalization.py` | `InitialInputNormalizer`: эффективные окна, аварии, слои, запросы матриц |
| `dto.py` | immutable вход/выход: snapshot, draft, `LayerMatrixRequest`, `Job`, `Engineer`, `PlanningLayer`, результат |
| `graph.py` | `LayeredGraphPlanner`: послойный граф, route columns, best-response, ejection, ALNS |
| `selection.py` | `GlobalRouteSelector`: branch-and-bound выбор непересекающихся колонок |
| `improvement.py` | `GreedyEjectionSearch`, `AdaptiveRouteImprover` (ALNS), архив колонок |
| `distribution.py` | eligibility, greedy insertion, official baseline, priority-append seed |
| `materialization.py` | точное расписание по выбранному порядку |
| `audit.py` | независимая проверка hard constraints и агрегатов |
| `diagnostics.py` | неперсистентный отчёт по стадиям, слоям, selector, ejection, ALNS |

## 2. Варианты

| Вариант | Состав | Где используется |
|---|---|---|
| `layered_graph` | граф + seeds + 2 best-response раунда + selector | production initial |
| `layered_graph_alns` | `layered_graph` + single-ejection + ALNS | эксперимент |
| `layered_graph_greedy` | `layered_graph` + greedy insertion остатков | сравнение |
| `greedy` | последовательная вставка без графа | сравнение, seed |
| `baseline` | п. 2.3 ТЗ: входной порядок, первый подходящий инженер, append-only | контроль, `BaselineResult` |

Все варианты проходят одну материализацию и один аудит; `algorithm_version` = `<variant>-v2`.

## 3. Параметры (`cfg.algorithm`)

| Параметр | Значение | Смысл |
|---|---|---|
| `emergency_response_minutes` | 120 | SLA начала работ по аварии |
| `priority_tier_weight` | 1000 | авария 1 000 000, подключение 1 000, ремонт 1 |
| `route_candidates_per_engineer` | 48 | колонок на инженера из первичного графа |
| `route_candidate_improvement_rounds` | 2 | best-response раунды |
| `route_candidates_per_improvement_round` | 4 | новых колонок на инженера за раунд |
| `alns_iterations` | 6 | итерации ALNS |
| `alns_candidates_per_repair` | 8 | колонок на repair-генерацию |
| `alns_cluster_fraction` | 0.25 | доля заявок в географическом кластере |
| `alns_random_seed` | 20260924 | seed детерминированного ALNS |

Переопределение для экспериментов: переменные окружения `ALGORITHM__<ПАРАМЕТР>`.

## 4. Исследовательский snapshot

Синтетический детерминированный набор, одинаковый для всех замеров:

- 3 инженера, смена 10:00–22:00, автомобиль, старты `(0,0)`, `(20,0)`, `(10,16)`;
  инженер 2 не имеет навыка аварийных работ;
- 48 заявок: 6 окон `10–12 … 20–22` по 8 заявок, 2 аварии в первом слое;
- приоритет: авария 1, каждая третья заявка 2, остальные 3;
- норматив `24 + (index * 7) mod 25` минут;
- матрица: манхэттенское расстояние `d`, минуты `max(1, round((2 + 2d) * k))`, км `d / 2`;
  коэффициент пробок слоя `k` = 1.15, 1.00, 1.10, 1.35, 1.25, 0.90;
- `calculation_cutoff_at = 10:00`.

Это smoke-исследование чистого алгоритма, не benchmark и не прогон на реальных данных 2ГИС/БД.
Скрипты генерации в репозиторий не добавлены: тестовой инфраструктуры в проекте нет.

## 5. Результаты

### 5.1 Сравнение вариантов, `min_engineers`

| Вариант | Назначено | Дорога, мин | Время |
|---|---|---|---|
| baseline | 31 / 48 | 1041 | 5 мс |
| greedy | 39 / 48 | 602 | 27 мс |
| layered_graph | 43 / 48 | 437 | 4,2 с |
| layered_graph_greedy | 43 / 48 | 437 | 4,3 с |
| layered_graph_alns | **45 / 48** | **338** | 7,0 с |

- Все результаты прошли аудит.
- Повторные прогоны `layered_graph` и `layered_graph_alns` идентичны.
- Аварии в `layered_graph_alns` начинаются в 10:12 и 10:59, SLA соблюдён.
- Baseline назначил только одну аварию из двух.
- Малые сценарии с аварией совпали с полным перебором: авария третьей с началом в 10:52
  и первой с началом в 10:08, когда иначе нарушается SLA.

### 5.2 Где тратится время

| Вариант | Генерация колонок | Selector | Запуски selector | Узлы B&B | Графовые прогоны |
|---|---|---|---|---|---|
| layered_graph | 4 205 мс | 11 мс | 3 | 4 035 | 11 |
| layered_graph_alns | 6 854 мс | 122 мс | 9 | 107 910 | 34 |

Материализация, метрики и аудит занимают меньше 1 мс. Узкое место — frontier графа.

### 5.3 Вклад стадий `layered_graph_alns`, `min_engineers`

| Итерации ALNS | Результат | Время | Улучшений ALNS | Cache hit/miss |
|---|---|---|---|---|
| 0 (только ejection) | 45 / 343 | 4,7 с | 0 | 0 / 11 |
| 6 | 45 / 338 | 7,0 с | 1 | 7 / 34 |
| 12 | 45 / 338 | 8,8 с | 1 | 20 / 51 |
| 24 | 45 / 338 | 10,6 с | 1 | 58 / 69 |

- Single-ejection: 43 попытки, 10 уникальных решений, 11 новых колонок.
- Он даёт +2 заявки и −94 минуты дороги примерно за 0,45 с.
- ALNS добавляет −5 минут за +2,3 с, затем насыщается.
- Seeds 1, 42 и 777 при 12 итерациях дают тот же 45 / 338.

### 5.4 Повторный ejection вне ALNS (эксперимент, не в коде)

Single-ejection, повторяемый от нового лучшего решения до отсутствия улучшения:

| Раунд | Результат | Накопленное время |
|---|---|---|
| 1 | 45 / 343 | 0,35 с |
| 2 | 45 / 339 | 0,64 с |
| 3 | 45 / 338 | 0,91 с |
| 4 | без улучшения | 1,21 с |

- Итог тот же, что у ALNS, но стоит примерно 0,9 с сверх графа вместо ~2,8 с.
- Парный eject (k ≤ 2) не улучшает 45 / 338 ни от этой точки, ни от результата ALNS; полный
  перебор пар занимает ~7,7 с.
- Значит, 45 / 338 — локальный оптимум для окрестностей 1- и 2-ejection на этом snapshot.

### 5.5 Режим `balanced`

`layered_graph` в режиме `balanced` даёт 43 / 457 с загрузкой 456 / 579 / 492 минуты.

`layered_graph_alns` в режиме `balanced`:

| Прогон | Результат | Загрузка, мин | Разброс |
|---|---|---|---|
| только ejection | 45 / 361 | 497 / 525 / 573 | 76 |
| 6 итераций | 45 / 356 | 497 / 540 / 573 | 76 |
| 12 итераций, seed 20260924 | 45 / 342 | 497 / 540 / 571 | 74 |
| 24 итерации, seed 20260924 | 45 / 342 | 497 / 540 / 571 | 74 |
| 12 итераций, seed 1 | 45 / 379 | 504 / 519 / 577 | 73 |
| 12 итераций, seed 42 | 45 / 437 | 515 / 540 / 553 | **38** |
| 12 итераций, seed 777 | 45 / 342 | 497 / 540 / 571 | 74 |

- В `balanced` разброс загрузки сравнивается раньше дороги, поэтому seed 42 нашёл вдвое
  лучшее по цели режима решение.
- Результат зависит от seed: поиск в этом режиме не сходится.
- Ejection в `balanced` запускается от двух seed-решений (`balanced` и `min_engineers`):
  86 попыток, 26 уникальных решений, 23 новые колонки.

## 6. Выводы и гипотезы

1. **`min_engineers`:** основной рычаг — ejection, а не ALNS. Гипотеза: заменить
   однопроходный `_improve_by_ejection` на повторяемый до сходимости; ожидаемо 45 / 338 за
   ~5,1 с против 7,0 с, ALNS для этого режима становится необязательным.
2. **`balanced`:** ALNS полезен, но недостаточно разнообразен. Кандидаты: несколько seed,
   destroy-оператор «самый загруженный + самый свободный инженер», повторный ejection с
   balanced-ключом.
3. **Производительность:** около 90 % времени — генерация frontier графа. Ускорять нужно
   граф (число прогонов, размер frontier), а не selector.
4. **Открыто:** достижимо ли покрытие больше 45 / 48. Физическая невыполнимость трёх
   оставшихся заявок не проверялась.
5. **Открыто:** переводить ли production initial с `layered_graph` на вариант с ejection.
   Сейчас production остаётся `layered_graph`, как предписывает A01.

## 7. Известные ограничения реализации

- Временный adapter в `src/api/planning/service.py` только вызывает алгоритм, 2ГИС и
  сохраняет результат. Pending-lifecycle по регионам, `partial_success`, откат округа и
  компенсация S3 — задача T03/G02.
- Baseline доступен как `plan_baseline(input)` и, для сравнительных прогонов, как
  `plan_initial(..., AlgorithmVariant.BASELINE)`; оба пути дают идентичный результат.
- Новый путь `prepare_initial → build_initial_input` на исследовательском snapshot даёт
  результаты, идентичные ручной сборке `InitialPlanningInput` (43/437, 45/338, 31/1041).
- Недостижимая пара точек 2ГИС прерывает расчёт округа (`DgisUnreachablePointsError`).
  Отдельной причины неназначения нет.
- Реальный прогон с 2ГИС и PostgreSQL на этом конвейере не выполнялся.
