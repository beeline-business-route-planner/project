import random
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache

from src.config import cfg
from src.core.algorithm.diagnostics import AlgorithmDiagnostics
from src.core.algorithm.dto import Engineer, InitialPlanningInput, Job
from src.core.algorithm.enums import RuinOperator
from src.core.algorithm.exc import AlgorithmInputError
from src.core.algorithm.materialization import ScheduleMaterializer
from src.core.algorithm.rules import PlanningRules
from src.core.algorithm.strategies.emergency import EmergencyPlanner
from src.core.algorithm.strategies.graph import LayeredGraphPlanner
from src.core.algorithm.strategies.greedy import GreedyPlanner
from src.core.db.enums import DistributionMode


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
    service_load_minutes: int


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
        self._emergency = EmergencyPlanner()
        self._graph = LayeredGraphPlanner()
        self._materializer = ScheduleMaterializer()
        self._diagnostics = diagnostics

    def assign(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        planning_input = replace(
            planning_input,
            jobs=tuple(sorted(planning_input.jobs, key=lambda job: job.id.int)),
            engineers=tuple(sorted(planning_input.engineers, key=lambda engineer: engineer.id.int)),
        )
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        layers_by_request = PlanningRules.index_layers(planning_input.layers, jobs_by_id)
        starts = [self._greedy.assign(planning_input)]
        emergency_start = self._emergency_start(planning_input)
        if emergency_start is not None:
            starts.append(emergency_start)
        for solution in planning_input.known_solutions:
            routes = self._materializer.feasible_routes(planning_input, solution, layers_by_request)
            if routes is not None:
                starts.append(routes)
        outcome = _LnsSearch(planning_input, self._graph, cfg.algorithm.lns_random_seed).run(starts)
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

    def _emergency_start(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]] | None:
        """Старт с максимумом аварий, дозаполненный greedy.

        Лучший план LNS не опускается ниже старта по ключу, а priority score аварии старше
        любого покрытия, поэтому итог назначает не меньше аварий, чем точная фаза.
        """

        emergency_routes = self._emergency.assign(planning_input)
        if emergency_routes is None:
            return None
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {
            engineer.id: () for engineer in planning_input.engineers
        } | emergency_routes
        assigned = {request_id for route in emergency_routes.values() for request_id in route}
        self._greedy.complete(
            [job for job in planning_input.jobs if job.id not in assigned], routes, planning_input
        )
        return {engineer_id: route for engineer_id, route in routes.items() if route}


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
        self._engineer_times = {
            engineer.id: (
                max(LayeredGraphPlanner.timestamp_us(engineer.available_from), self._cutoff_us),
                LayeredGraphPlanner.timestamp_us(engineer.shift_end),
            )
            for engineer in self._engineers
        }
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
        self._travel_cache: dict[tuple[str, int, int], int] = {}
        self._min_engineers = planning_input.mode == DistributionMode.MIN_ENGINEERS
        self._operator_uses = dict.fromkeys(RuinOperator, 0)
        self._descent_attempts = 0
        self._cached_schedule = lru_cache(maxsize=8192)(self._compute_schedule)

    def run(self, starts: Sequence[dict[uuid.UUID, tuple[uuid.UUID, ...]]]) -> _SearchOutcome:
        """Ищет от лучшего из допустимых стартовых решений (greedy и известные решения)."""

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
        best = self._descend_between_routes(best)
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
            used_count += (
                bool(schedule.request_ids) or schedule.engineer.history_service_minutes > 0
            )
            travel_minutes += sum(schedule.travel_in)
            service_loads.append(schedule.service_load_minutes)
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
        removal_count = min(
            len(assigned), max(2, min(len(assigned) // 4, int(len(assigned) * fraction)))
        )
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
            opens_new_engineer = (
                not schedule.request_ids and schedule.engineer.history_service_minutes == 0
            )
            return cfg.algorithm.lns_new_route_penalty_minutes if opens_new_engineer else 0
        return self._service_minutes(schedule) * cfg.algorithm.lns_balance_load_weight

    def _best_insertion(self, schedule: _RouteSchedule, request_id: uuid.UUID) -> _Insertion | None:
        engineer = schedule.engineer
        timing = self._timings[request_id]
        route_start_us, shift_end_us = self._engineer_times[engineer.id]
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

    def _descend_between_routes(
        self, routes: dict[uuid.UUID, _RouteSchedule]
    ) -> dict[uuid.UUID, _RouteSchedule]:
        """Локальный спуск межмаршрутными ходами: перенос, обмен, обмен хвостов.

        Первый найденный в детерминированном порядке ход со строго лучшим полным ключом
        применяется сразу. Спуск завершается при отсутствии улучшений или исчерпании
        бюджета попыток. Изменённые маршруты затем переоптимизирует граф.
        """

        routes = dict(routes)
        key = self._key(routes)
        changed: set[uuid.UUID] = set()
        while self._descent_attempts < cfg.algorithm.lns_descent_attempt_budget:
            move = self._improving_relocate(routes, key)
            if move is None and self._descent_attempts < cfg.algorithm.lns_descent_attempt_budget:
                move = self._improving_swap(routes, key)
            if move is None and self._descent_attempts < cfg.algorithm.lns_descent_attempt_budget:
                move = self._improving_tail_exchange(routes, key)
            if move is None:
                break
            routes.update(move)
            changed.update(move)
            key = self._key(routes)
        return self._polish(routes, changed)

    def _improving_relocate(
        self,
        routes: dict[uuid.UUID, _RouteSchedule],
        key: tuple[int, int, int, int],
    ) -> dict[uuid.UUID, _RouteSchedule] | None:
        ordered = sorted(routes.values(), key=lambda schedule: schedule.engineer.id.int)
        for source in ordered:
            for index, request_id in enumerate(source.request_ids):
                reduced = self._schedule(
                    source.engineer,
                    (*source.request_ids[:index], *source.request_ids[index + 1 :]),
                )
                if reduced is None:
                    continue
                for target in ordered:
                    if target is source or request_id not in self._eligible_ids[target.engineer.id]:
                        continue
                    if (
                        self._min_engineers
                        and reduced.request_ids
                        and not target.request_ids
                        and target.engineer.history_service_minutes == 0
                    ):
                        continue
                    if not self._try_descent_attempt():
                        return None
                    grown = self._inserted(target, request_id)
                    if grown is None:
                        continue
                    move = {source.engineer.id: reduced, target.engineer.id: grown}
                    if self._move_key(routes, key, move) > key:
                        return move
        return None

    def _improving_swap(
        self,
        routes: dict[uuid.UUID, _RouteSchedule],
        key: tuple[int, int, int, int],
    ) -> dict[uuid.UUID, _RouteSchedule] | None:
        """Обмен двух заявок одного окна между бригадами, каждая — на свою лучшую позицию."""

        ordered = sorted(routes.values(), key=lambda schedule: schedule.engineer.id.int)
        reduced: dict[uuid.UUID, dict[int, _RouteSchedule | None]] = {}
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                for left_position, left_id in enumerate(left.request_ids):
                    if left_id not in self._eligible_ids[right.engineer.id]:
                        continue
                    for right_position, right_id in enumerate(right.request_ids):
                        if (
                            right_id not in self._eligible_ids[left.engineer.id]
                            or self._timings[right_id].window_start
                            != self._timings[left_id].window_start
                        ):
                            continue
                        if not self._try_descent_attempt():
                            return None
                        left_cache = reduced.setdefault(left.engineer.id, {})
                        if left_position not in left_cache:
                            left_cache[left_position] = self._schedule(
                                left.engineer,
                                (
                                    *left.request_ids[:left_position],
                                    *left.request_ids[left_position + 1 :],
                                ),
                            )
                        right_cache = reduced.setdefault(right.engineer.id, {})
                        if right_position not in right_cache:
                            right_cache[right_position] = self._schedule(
                                right.engineer,
                                (
                                    *right.request_ids[:right_position],
                                    *right.request_ids[right_position + 1 :],
                                ),
                            )
                        left_reduced = left_cache[left_position]
                        right_reduced = right_cache[right_position]
                        if left_reduced is None or right_reduced is None:
                            continue
                        move = self._swapped(
                            left_reduced,
                            left_id,
                            right_reduced,
                            right_id,
                        )
                        if move is not None and self._move_key(routes, key, move) > key:
                            return move
        return None

    def _swapped(
        self,
        left_reduced: _RouteSchedule,
        left_id: uuid.UUID,
        right_reduced: _RouteSchedule,
        right_id: uuid.UUID,
    ) -> dict[uuid.UUID, _RouteSchedule] | None:
        new_left = self._inserted(left_reduced, right_id)
        new_right = self._inserted(right_reduced, left_id)
        if new_left is None or new_right is None:
            return None
        return {left_reduced.engineer.id: new_left, right_reduced.engineer.id: new_right}

    def _improving_tail_exchange(
        self,
        routes: dict[uuid.UUID, _RouteSchedule],
        key: tuple[int, int, int, int],
    ) -> dict[uuid.UUID, _RouteSchedule] | None:
        """2-opt*: бригады обмениваются хвостами маршрутов после точек разреза."""

        ordered = sorted(routes.values(), key=lambda schedule: schedule.engineer.id.int)
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                for left_cut in range(len(left.request_ids) + 1):
                    left_tail = left.request_ids[left_cut:]
                    if not self._eligible_ids[right.engineer.id].issuperset(left_tail):
                        continue
                    for right_cut in range(len(right.request_ids) + 1):
                        right_tail = right.request_ids[right_cut:]
                        if not (left_tail or right_tail) or not self._eligible_ids[
                            left.engineer.id
                        ].issuperset(right_tail):
                            continue
                        left_ids = (*left.request_ids[:left_cut], *right_tail)
                        right_ids = (*right.request_ids[:right_cut], *left_tail)
                        if self._min_engineers:
                            old_used = (
                                bool(left.request_ids) or left.engineer.history_service_minutes > 0
                            ) + (
                                bool(right.request_ids)
                                or right.engineer.history_service_minutes > 0
                            )
                            new_used = (
                                bool(left_ids) or left.engineer.history_service_minutes > 0
                            ) + (bool(right_ids) or right.engineer.history_service_minutes > 0)
                            if new_used > old_used:
                                continue
                        if not self._try_descent_attempt():
                            return None
                        if (
                            left_cut
                            and right_tail
                            and self._timings[left.request_ids[left_cut - 1]].window_start
                            > self._timings[right_tail[0]].window_start
                        ) or (
                            right_cut
                            and left_tail
                            and self._timings[right.request_ids[right_cut - 1]].window_start
                            > self._timings[left_tail[0]].window_start
                        ):
                            continue
                        new_left = self._schedule(left.engineer, left_ids)
                        new_right = self._schedule(right.engineer, right_ids)
                        if new_left is None or new_right is None:
                            continue
                        move = {left.engineer.id: new_left, right.engineer.id: new_right}
                        if self._move_key(routes, key, move) > key:
                            return move
        return None

    def _move_key(
        self,
        routes: dict[uuid.UUID, _RouteSchedule],
        key: tuple[int, int, int, int],
        move: dict[uuid.UUID, _RouteSchedule],
    ) -> tuple[int, int, int, int]:
        """Оценивает перестановку заявок по изменённым маршрутам.

        Relocate, swap и обмен хвостов сохраняют набор заявок, поэтому приоритет и
        покрытие не меняются. В balanced разброс считается по закэшированной нагрузке
        всех маршрутов, без повторного суммирования заявок.
        """

        old_used = sum(
            bool(routes[engineer_id].request_ids)
            or routes[engineer_id].engineer.history_service_minutes > 0
            for engineer_id in move
        )
        new_used = sum(
            bool(schedule.request_ids) or schedule.engineer.history_service_minutes > 0
            for schedule in move.values()
        )
        old_travel = sum(sum(routes[engineer_id].travel_in) for engineer_id in move)
        new_travel = sum(sum(schedule.travel_in) for schedule in move.values())
        mode_score = key[2] + old_used - new_used
        if not self._min_engineers:
            loads = [
                move.get(engineer_id, schedule).service_load_minutes
                for engineer_id, schedule in routes.items()
            ]
            mode_score = -(max(loads, default=0) - min(loads, default=0))
        return key[0], key[1], mode_score, key[3] + old_travel - new_travel

    def _try_descent_attempt(self) -> bool:
        if self._descent_attempts >= cfg.algorithm.lns_descent_attempt_budget:
            return False
        self._descent_attempts += 1
        return True

    def _inserted(self, schedule: _RouteSchedule, request_id: uuid.UUID) -> _RouteSchedule | None:
        """Вставляет заявку на позицию с наименьшим приростом дороги."""

        insertion = self._best_insertion(schedule, request_id)
        if insertion is None:
            return None
        return self._schedule(
            schedule.engineer,
            (
                *schedule.request_ids[: insertion.position],
                request_id,
                *schedule.request_ids[insertion.position :],
            ),
        )

    def _schedule(
        self, engineer: Engineer, request_ids: tuple[uuid.UUID, ...]
    ) -> _RouteSchedule | None:
        return self._cached_schedule(engineer, request_ids)

    def _compute_schedule(
        self, engineer: Engineer, request_ids: tuple[uuid.UUID, ...]
    ) -> _RouteSchedule | None:
        """Материализует порядок в целых микросекундах и считает max-shift с конца."""

        previous_id = engineer.id
        previous_finish, shift_end_us = self._engineer_times[engineer.id]
        previous_window: datetime | None = None
        starts: list[int] = []
        finishes: list[int] = []
        travel_in: list[int] = []
        service_load_minutes = engineer.history_service_minutes
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
            service_load_minutes += self._jobs_by_id[request_id].service_minutes
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
            service_load_minutes=service_load_minutes,
        )

    @staticmethod
    def _empty_schedule(engineer: Engineer) -> _RouteSchedule:
        return _RouteSchedule(engineer, (), (), (), (), (), engineer.history_service_minutes)

    def _travel(self, engineer: Engineer, from_id: uuid.UUID, to_id: uuid.UUID) -> int:
        key = (engineer.vehicle_type.value, from_id.int, to_id.int)
        cached = self._travel_cache.get(key)
        if cached is None:
            cached = LayeredGraphPlanner.travel_minutes(
                self._layers_by_request[to_id], engineer, from_id, to_id
            )
            self._travel_cache[key] = cached
        return cached

    def _service_minutes(self, schedule: _RouteSchedule) -> int:
        """Работа бригады за день: прожитая история replan и будущие заявки."""

        return schedule.service_load_minutes

    @staticmethod
    def _squared_distance(left: Job, right: Job) -> float:
        latitude = float(left.latitude - right.latitude)
        longitude = float(left.longitude - right.longitude)
        return latitude * latitude + longitude * longitude
