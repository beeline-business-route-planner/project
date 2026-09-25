import random
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from src.config import cfg
from src.core.algorithm.diagnostics import AlgorithmDiagnostics
from src.core.algorithm.dto import Engineer, InitialPlanningInput, Job
from src.core.algorithm.enums import DistributionMode, RuinOperator
from src.core.algorithm.exc import AlgorithmInputError
from src.core.algorithm.rules import PlanningRules
from src.core.algorithm.strategies.graph import LayeredGraphPlanner
from src.core.algorithm.strategies.greedy import GreedyPlanner


@dataclass(frozen=True)
class _JobTiming:
    release_us: int
    latest_us: int
    service_us: int
    window_start: datetime
    priority_score: int


@dataclass(frozen=True)
class _RouteSchedule:
    """Маршрут с расписанием и запасом сдвига каждой остановки (max-shift).

    `max_shift_us[i]` — на сколько можно отложить начало остановки `i`, не нарушив её
    окно, окна следующих остановок и конец смены. Это делает проверку вставки O(1).
    """

    engineer: Engineer
    request_ids: tuple[uuid.UUID, ...]
    starts_us: tuple[int, ...]
    finishes_us: tuple[int, ...]
    travel_in: tuple[int, ...]
    max_shift_us: tuple[int, ...]


@dataclass(frozen=True)
class _SearchOutcome:
    routes: dict[uuid.UUID, tuple[uuid.UUID, ...]]
    accepted_count: int
    improvements_count: int
    operator_uses: dict[RuinOperator, int]


@dataclass(frozen=True)
class _Insertion:
    added_travel: int
    position: int


class LnsPlanner:
    """Large Neighborhood Search: разрушение части плана и regret-сборка с полировкой графом.

    Старт — greedy. Каждая итерация снимает часть назначенных заявок одним из операторов
    разрушения, затем вставляет снятые и нераспределённые заявки regret-вставкой (первой
    идёт заявка, которую дороже всего отложить) и переоптимизирует маршрут каждого
    изменённого инженера точным послойным графом по пулу «его заявки + свободные».
    План принимается, если приоритет, покрытие и цель режима не хуже текущих, а дорога
    хуже не больше чем на убывающий порог. Лучший план запоминается отдельно.
    Весь случайный выбор идёт от фиксированного seed, бюджет — число итераций.
    """

    def __init__(self, diagnostics: AlgorithmDiagnostics | None = None) -> None:
        self._greedy = GreedyPlanner()
        self._graph = LayeredGraphPlanner()
        self._diagnostics = diagnostics

    def assign(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        outcome = _LnsSearch(planning_input, self._graph, cfg.algorithm.lns_random_seed).run(
            [self._greedy.assign(planning_input)]
        )
        if self._diagnostics is not None:
            self._diagnostics.record_lns_search(
                iterations_count=cfg.algorithm.lns_iterations,
                accepted_count=outcome.accepted_count,
                improvements_count=outcome.improvements_count,
                operator_uses=tuple(
                    (operator.value, outcome.operator_uses[operator]) for operator in RuinOperator
                ),
            )
        return outcome.routes


class _LnsSearch:
    """Состояние одного запуска LNS: индексы входа, кэш дороги и генератор случайности."""

    def __init__(
        self,
        planning_input: InitialPlanningInput,
        graph: LayeredGraphPlanner,
        random_seed: int,
    ) -> None:
        self._input = planning_input
        self._graph = graph
        self._random = random.Random(random_seed)
        self._jobs_by_id = {job.id: job for job in planning_input.jobs}
        self._job_positions = {job.id: index for index, job in enumerate(planning_input.jobs)}
        self._layers_by_request = PlanningRules.index_layers(
            planning_input.layers, self._jobs_by_id
        )
        self._engineers = tuple(
            engineer for engineer in planning_input.engineers if engineer.is_available
        )
        self._eligible_ids = {
            engineer.id: frozenset(
                job.id for job in planning_input.jobs if PlanningRules.eligible(engineer, job)
            )
            for engineer in self._engineers
        }
        self._cutoff_us = LayeredGraphPlanner.timestamp_us(planning_input.calculation_cutoff_at)
        self._timings = {
            job.id: _JobTiming(
                release_us=LayeredGraphPlanner.timestamp_us(job.release_at),
                latest_us=LayeredGraphPlanner.timestamp_us(job.latest_start_at),
                service_us=job.service_minutes * 60_000_000,
                window_start=self._layers_by_request[job.id].window_start,
                priority_score=PlanningRules.priority_score(job.priority),
            )
            for job in planning_input.jobs
        }
        self._travel_cache: dict[tuple[str, uuid.UUID, uuid.UUID], int] = {}
        self._min_engineers = planning_input.mode == DistributionMode.MIN_ENGINEERS
        self._operator_uses = dict.fromkeys(RuinOperator, 0)

    def run(self, starts: Sequence[dict[uuid.UUID, tuple[uuid.UUID, ...]]]) -> _SearchOutcome:
        """Ищет от лучшего из стартовых решений."""

        routes = max(
            (self._start_routes(start) for start in starts),
            key=self._key,
        )
        current, current_key = routes, self._key(routes)
        best, best_key = current, current_key
        iterations = cfg.algorithm.lns_iterations
        accepted_count = 0
        improvements_count = 0
        for iteration in range(iterations):
            operator = self._choose_operator()
            candidate = self._ruin(current, operator)
            candidate = self._recreate(candidate)
            changed = {
                engineer_id
                for engineer_id, schedule in candidate.items()
                if schedule.request_ids != current[engineer_id].request_ids
            }
            candidate = self._polish(candidate, changed)
            candidate_key = self._key(candidate)
            threshold = cfg.algorithm.lns_acceptance_threshold * (1 - iteration / iterations)
            if candidate_key[:3] > current_key[:3] or (
                candidate_key[:3] == current_key[:3]
                and -candidate_key[3] <= -current_key[3] * (1 + threshold)
            ):
                current, current_key = candidate, candidate_key
                accepted_count += 1
            if candidate_key > best_key:
                best, best_key = candidate, candidate_key
                improvements_count += 1
        return _SearchOutcome(
            routes={
                engineer_id: schedule.request_ids
                for engineer_id, schedule in best.items()
                if schedule.request_ids
            },
            accepted_count=accepted_count,
            improvements_count=improvements_count,
            operator_uses=dict(self._operator_uses),
        )

    def _start_routes(
        self, start: dict[uuid.UUID, tuple[uuid.UUID, ...]]
    ) -> dict[uuid.UUID, _RouteSchedule]:
        routes: dict[uuid.UUID, _RouteSchedule] = {}
        for engineer in self._engineers:
            schedule = self._schedule(engineer, start.get(engineer.id, ()))
            routes[engineer.id] = (
                schedule if schedule is not None else self._empty_schedule(engineer)
            )
        return self._polish(self._recreate(routes), set(routes))

    def _key(self, routes: dict[uuid.UUID, _RouteSchedule]) -> tuple[int, int, int, int]:
        """Иерархия цели: priority score → покрытие → цель режима → дорога."""

        priority_score = 0
        assigned_count = 0
        used_count = 0
        travel_minutes = 0
        service_loads: list[int] = []
        for schedule in routes.values():
            priority_score += sum(
                self._timings[request_id].priority_score for request_id in schedule.request_ids
            )
            assigned_count += len(schedule.request_ids)
            used_count += bool(schedule.request_ids)
            travel_minutes += sum(schedule.travel_in)
            service_loads.append(self._service_minutes(schedule))
        mode_score = (
            -used_count
            if self._min_engineers
            else -(max(service_loads, default=0) - min(service_loads, default=0))
        )
        return priority_score, assigned_count, mode_score, -travel_minutes

    def _choose_operator(self) -> RuinOperator:
        operator = self._random.choice(tuple(RuinOperator))
        self._operator_uses[operator] += 1
        return operator

    def _ruin(
        self, routes: dict[uuid.UUID, _RouteSchedule], operator: RuinOperator
    ) -> dict[uuid.UUID, _RouteSchedule]:
        assigned = sorted(
            (request_id for schedule in routes.values() for request_id in schedule.request_ids),
            key=self._job_positions.__getitem__,
        )
        if not assigned:
            return routes
        fraction = self._random.uniform(
            cfg.algorithm.lns_min_removal_fraction, cfg.algorithm.lns_max_removal_fraction
        )
        removal_count = max(2, min(len(assigned) // 4, int(len(assigned) * fraction)))
        removed = self._removed_ids(routes, assigned, removal_count, operator)
        return {
            engineer_id: (
                self._schedule(
                    schedule.engineer,
                    tuple(
                        request_id
                        for request_id in schedule.request_ids
                        if request_id not in removed
                    ),
                )
                or self._empty_schedule(schedule.engineer)
            )
            if removed.intersection(schedule.request_ids)
            else schedule
            for engineer_id, schedule in routes.items()
        }

    def _removed_ids(
        self,
        routes: dict[uuid.UUID, _RouteSchedule],
        assigned: list[uuid.UUID],
        removal_count: int,
        operator: RuinOperator,
    ) -> set[uuid.UUID]:
        match operator:
            case RuinOperator.RANDOM:
                return set(self._random.sample(assigned, removal_count))
            case RuinOperator.RELATED:
                return set(self._nearest(self._random.choice(assigned), assigned)[:removal_count])
            case RuinOperator.ROUTE:
                used = [schedule for schedule in routes.values() if schedule.request_ids]
                picked = self._random.sample(used, min(3, len(used)))
                return set(min(picked, key=lambda schedule: len(schedule.request_ids)).request_ids)
            case RuinOperator.TIME_WINDOW:
                window_start = self._timings[self._random.choice(assigned)].window_start
                same_window = [
                    request_id
                    for request_id in assigned
                    if self._timings[request_id].window_start == window_start
                ]
                if len(same_window) > 2 * removal_count:
                    return set(self._random.sample(same_window, 2 * removal_count))
                return set(same_window)
            case RuinOperator.STRING:
                return self._string_removal(routes, assigned, removal_count)
            case RuinOperator.WORST:
                return self._worst_removal(routes, removal_count)

    def _string_removal(
        self,
        routes: dict[uuid.UUID, _RouteSchedule],
        assigned: list[uuid.UUID],
        removal_count: int,
    ) -> set[uuid.UUID]:
        """Снимает короткие цепочки подряд идущих остановок у маршрутов вокруг случайной заявки."""

        owner_by_request = {
            request_id: engineer_id
            for engineer_id, schedule in routes.items()
            for request_id in schedule.request_ids
        }
        removed: set[uuid.UUID] = set()
        touched: set[uuid.UUID] = set()
        for request_id in self._nearest(self._random.choice(assigned), assigned):
            if len(removed) >= removal_count:
                break
            owner = owner_by_request[request_id]
            if owner in touched:
                continue
            touched.add(owner)
            request_ids = routes[owner].request_ids
            index = request_ids.index(request_id)
            length = self._random.randint(1, 4)
            start = max(0, index - self._random.randint(0, length - 1))
            removed.update(request_ids[start : start + length])
        return removed

    def _worst_removal(
        self, routes: dict[uuid.UUID, _RouteSchedule], removal_count: int
    ) -> set[uuid.UUID]:
        """Снимает заявки с наибольшим крюком: насколько сократится дорога без остановки.

        Список крюков упорядочен по убыванию, индекс выбирается как `n * u**3`
        (u равномерно на [0, 1)), поэтому дорогие остановки выбираются чаще, но не всегда.
        """

        detours: list[tuple[int, int, uuid.UUID]] = []
        for schedule in routes.values():
            request_ids = schedule.request_ids
            for index, request_id in enumerate(request_ids):
                previous_id = request_ids[index - 1] if index else schedule.engineer.id
                detour = schedule.travel_in[index]
                if index + 1 < len(request_ids):
                    next_id = request_ids[index + 1]
                    detour += schedule.travel_in[index + 1] - self._travel(
                        schedule.engineer, previous_id, next_id
                    )
                detours.append((-detour, self._job_positions[request_id], request_id))
        detours.sort()
        removed: set[uuid.UUID] = set()
        while len(removed) < min(removal_count, len(detours)):
            index = int(len(detours) * self._random.random() ** 3)
            removed.add(detours[index][2])
        return removed

    def _nearest(self, pivot_id: uuid.UUID, request_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        pivot = self._jobs_by_id[pivot_id]
        return sorted(
            request_ids,
            key=lambda request_id: (
                self._squared_distance(pivot, self._jobs_by_id[request_id]),
                self._job_positions[request_id],
            ),
        )

    def _recreate(self, routes: dict[uuid.UUID, _RouteSchedule]) -> dict[uuid.UUID, _RouteSchedule]:
        """Regret-2 вставка всех нераспределённых заявок, пока находится допустимая позиция."""

        routes = dict(routes)
        assigned = {
            request_id for schedule in routes.values() for request_id in schedule.request_ids
        }
        pool = sorted(
            (job.id for job in self._input.jobs if job.id not in assigned),
            key=self._job_positions.__getitem__,
        )
        insertions: dict[tuple[uuid.UUID, uuid.UUID], _Insertion | None] = {}
        stale_engineers = set(routes)
        while pool:
            for engineer_id in stale_engineers:
                for request_id in pool:
                    if request_id in self._eligible_ids[engineer_id]:
                        insertions[request_id, engineer_id] = self._best_insertion(
                            routes[engineer_id], request_id
                        )
            choice = self._regret_choice(routes, pool, insertions)
            if choice is None:
                break
            request_id, engineer_id, position = choice
            schedule = routes[engineer_id]
            inserted = self._schedule(
                schedule.engineer,
                (
                    *schedule.request_ids[:position],
                    request_id,
                    *schedule.request_ids[position:],
                ),
            )
            if inserted is None:
                raise AlgorithmInputError("Допустимая по max-shift вставка не материализуется")
            routes[engineer_id] = inserted
            pool.remove(request_id)
            stale_engineers = {engineer_id}
        return routes

    def _regret_choice(
        self,
        routes: dict[uuid.UUID, _RouteSchedule],
        pool: list[uuid.UUID],
        insertions: dict[tuple[uuid.UUID, uuid.UUID], _Insertion | None],
    ) -> tuple[uuid.UUID, uuid.UUID, int] | None:
        noise = cfg.algorithm.lns_insertion_noise
        best_key: tuple[int, float, float, int] | None = None
        best_choice: tuple[uuid.UUID, uuid.UUID, int] | None = None
        for request_id in pool:
            options: list[tuple[float, int, uuid.UUID, int]] = []
            for engineer in self._engineers:
                insertion = insertions.get((request_id, engineer.id))
                if insertion is None:
                    continue
                cost = insertion.added_travel * (1 + noise * self._random.uniform(-1, 1))
                cost += self._opening_cost(routes[engineer.id])
                options.append((cost, engineer.id.int, engineer.id, insertion.position))
            if not options:
                continue
            options.sort()
            regret = options[1][0] - options[0][0] if len(options) > 1 else float("inf")
            key = (
                self._timings[request_id].priority_score,
                regret,
                -options[0][0],
                -self._job_positions[request_id],
            )
            if best_key is None or key > best_key:
                best_key = key
                best_choice = (request_id, options[0][2], options[0][3])
        return best_choice

    def _opening_cost(self, schedule: _RouteSchedule) -> float:
        """Штраф режима: открыть новый маршрут (min_engineers) или нагрузить занятого (balanced)."""

        if self._min_engineers:
            return cfg.algorithm.lns_new_route_penalty_minutes if not schedule.request_ids else 0
        return self._service_minutes(schedule) * cfg.algorithm.lns_balance_load_weight

    def _best_insertion(self, schedule: _RouteSchedule, request_id: uuid.UUID) -> _Insertion | None:
        engineer = schedule.engineer
        timing = self._timings[request_id]
        shift_end_us = LayeredGraphPlanner.timestamp_us(engineer.shift_end)
        route_start_us = max(
            LayeredGraphPlanner.timestamp_us(engineer.available_from), self._cutoff_us
        )
        request_ids = schedule.request_ids
        best: _Insertion | None = None
        for position in range(len(request_ids) + 1):
            if (
                position
                and self._timings[request_ids[position - 1]].window_start > timing.window_start
            ):
                continue
            if (
                position < len(request_ids)
                and self._timings[request_ids[position]].window_start < timing.window_start
            ):
                break
            previous_id = request_ids[position - 1] if position else engineer.id
            previous_finish = schedule.finishes_us[position - 1] if position else route_start_us
            travel_to = self._travel(engineer, previous_id, request_id)
            start = max(
                previous_finish + travel_to * 60_000_000, timing.release_us, self._cutoff_us
            )
            finish = start + timing.service_us
            if start > timing.latest_us or finish > shift_end_us:
                continue
            added_travel = travel_to
            if position < len(request_ids):
                next_id = request_ids[position]
                travel_from = self._travel(engineer, request_id, next_id)
                next_start = max(
                    finish + travel_from * 60_000_000,
                    self._timings[next_id].release_us,
                    self._cutoff_us,
                )
                if next_start - schedule.starts_us[position] > schedule.max_shift_us[position]:
                    continue
                added_travel += travel_from - schedule.travel_in[position]
            if best is None or added_travel < best.added_travel:
                best = _Insertion(added_travel=added_travel, position=position)
        return best

    def _polish(
        self,
        routes: dict[uuid.UUID, _RouteSchedule],
        engineer_ids: Iterable[uuid.UUID],
    ) -> dict[uuid.UUID, _RouteSchedule]:
        """Точный граф переоптимизирует маршрут по пулу «свои заявки + свободные»."""

        routes = dict(routes)
        assigned = {
            request_id for schedule in routes.values() for request_id in schedule.request_ids
        }
        for engineer_id in sorted(engineer_ids, key=lambda item: item.int):
            schedule = routes[engineer_id]
            free_ids = [
                job.id
                for job in self._input.jobs
                if job.id not in assigned and job.id in self._eligible_ids[engineer_id]
            ]
            if not free_ids and len(schedule.request_ids) < 2:
                continue
            path, priority_score, travel_minutes = self._graph.best_route(
                schedule.engineer,
                [self._jobs_by_id[request_id] for request_id in (*schedule.request_ids, *free_ids)],
                self._layers_by_request,
                self._input.calculation_cutoff_at,
                self._job_positions,
            )
            current = (
                sum(
                    self._timings[request_id].priority_score for request_id in schedule.request_ids
                ),
                len(schedule.request_ids),
                -sum(schedule.travel_in),
            )
            if (priority_score, len(path), -travel_minutes) <= current:
                continue
            polished = self._schedule(schedule.engineer, path)
            if polished is None:
                raise AlgorithmInputError("Маршрут графа не материализуется")
            assigned.difference_update(schedule.request_ids)
            assigned.update(path)
            routes[engineer_id] = polished
        return routes

    def _schedule(
        self, engineer: Engineer, request_ids: tuple[uuid.UUID, ...]
    ) -> _RouteSchedule | None:
        """Материализует порядок в целых микросекундах и считает max-shift с конца."""

        previous_id = engineer.id
        previous_finish = max(
            LayeredGraphPlanner.timestamp_us(engineer.available_from), self._cutoff_us
        )
        shift_end_us = LayeredGraphPlanner.timestamp_us(engineer.shift_end)
        previous_window: datetime | None = None
        starts: list[int] = []
        finishes: list[int] = []
        travel_in: list[int] = []
        for request_id in request_ids:
            timing = self._timings[request_id]
            if previous_window is not None and timing.window_start < previous_window:
                return None
            travel = self._travel(engineer, previous_id, request_id)
            start = max(previous_finish + travel * 60_000_000, timing.release_us, self._cutoff_us)
            finish = start + timing.service_us
            if start > timing.latest_us or finish > shift_end_us:
                return None
            starts.append(start)
            finishes.append(finish)
            travel_in.append(travel)
            previous_id, previous_finish, previous_window = request_id, finish, timing.window_start
        max_shift = [0] * len(request_ids)
        for index in range(len(request_ids) - 1, -1, -1):
            if index == len(request_ids) - 1:
                tail = shift_end_us - finishes[index]
            else:
                arrival = finishes[index] + travel_in[index + 1] * 60_000_000
                tail = starts[index + 1] - arrival + max_shift[index + 1]
            max_shift[index] = min(
                self._timings[request_ids[index]].latest_us - starts[index], tail
            )
        return _RouteSchedule(
            engineer=engineer,
            request_ids=request_ids,
            starts_us=tuple(starts),
            finishes_us=tuple(finishes),
            travel_in=tuple(travel_in),
            max_shift_us=tuple(max_shift),
        )

    @staticmethod
    def _empty_schedule(engineer: Engineer) -> _RouteSchedule:
        return _RouteSchedule(engineer, (), (), (), (), ())

    def _travel(self, engineer: Engineer, from_id: uuid.UUID, to_id: uuid.UUID) -> int:
        key = (engineer.vehicle_type.value, from_id, to_id)
        cached = self._travel_cache.get(key)
        if cached is None:
            cached = LayeredGraphPlanner.travel_minutes(
                self._layers_by_request[to_id], engineer, from_id, to_id
            )
            self._travel_cache[key] = cached
        return cached

    def _service_minutes(self, schedule: _RouteSchedule) -> int:
        return sum(
            self._jobs_by_id[request_id].service_minutes for request_id in schedule.request_ids
        )

    @staticmethod
    def _squared_distance(left: Job, right: Job) -> float:
        latitude = float(left.latitude - right.latitude)
        longitude = float(left.longitude - right.longitude)
        return latitude * latitude + longitude * longitude
