import uuid
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from src.config import cfg
from src.core.algorithm.diagnostics import AlgorithmDiagnostics
from src.core.algorithm.dto import (
    CandidateSelectionResult,
    Engineer,
    InitialPlanningInput,
    Job,
    PlanningLayer,
    RouteCandidate,
)
from src.core.algorithm.exc import AlgorithmInputError
from src.core.algorithm.materialization import ScheduleMaterializer
from src.core.algorithm.rules import PlanningRules
from src.core.algorithm.strategies.baseline import BaselinePlanner
from src.core.algorithm.strategies.greedy import GreedyPlanner
from src.core.algorithm.strategies.selection import GlobalRouteSelector
from src.core.db.enums import DistributionMode


@dataclass(frozen=True, slots=True)
class _GraphState:
    """Достижимое состояние маршрута после нуля или нескольких заявок слоя.

    Время хранится целыми микросекундами, а последняя точка и путь — ещё и целыми UUID: граф
    сравнивает сотни тысяч состояний, и арифметика datetime/хэширование UUID доминируют во
    времени. Маска посещённых заявок слоя живёт только внутри слоя рядом с состоянием.
    """

    last_int: int
    finish_us: int
    travel_minutes: int
    priority_score: int
    path: tuple[uuid.UUID, ...]
    path_ints: tuple[int, ...]


@dataclass(slots=True)
class _LayerSearchCounts:
    """Счётчики перебора одного слоя для диагностики."""

    input_states_count: int
    transition_attempts_count: int = 0
    feasible_transitions_count: int = 0
    rejected_by_time_count: int = 0
    rejected_by_pareto_count: int = 0
    pruned_by_pareto_count: int = 0


class LayeredGraphPlanner:
    """Планирует инженеров точным графом состояний по временным окнам заявок."""

    def __init__(self, diagnostics: AlgorithmDiagnostics | None = None) -> None:
        self._greedy = GreedyPlanner()
        self._baseline = BaselinePlanner()
        self._selector = GlobalRouteSelector()
        self._materializer = ScheduleMaterializer()
        self._diagnostics = diagnostics
        self._state_cache: dict[tuple[uuid.UUID, int], tuple[_GraphState, ...]] = {}
        self._travel_cache: dict[tuple[str, uuid.UUID, uuid.UUID], int] = {}
        self._reference_solutions: list[dict[uuid.UUID, tuple[uuid.UUID, ...]]] = []
        self._cache_hits_count = 0
        self._cache_misses_count = 0

    def assign(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        self._state_cache.clear()
        self._travel_cache.clear()
        self._reference_solutions.clear()
        self._cache_hits_count = 0
        self._cache_misses_count = 0
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        layers_by_request = PlanningRules.index_layers(planning_input.layers, jobs_by_id)
        job_positions = {job.id: position for position, job in enumerate(planning_input.jobs)}
        baseline_routes = self._baseline.assign(planning_input)
        seed_inputs = tuple(replace(planning_input, mode=mode) for mode in DistributionMode)
        seed_routes = tuple(
            routes
            for seed_input in seed_inputs
            for routes in (
                self._greedy.assign(seed_input),
                self._greedy.assign_priority_append_seed(seed_input),
            )
        )
        known_routes = tuple(
            routes
            for solution in planning_input.known_solutions
            if (
                routes := self._materializer.feasible_routes(
                    planning_input, solution, layers_by_request
                )
            )
            is not None
        )
        seed_routes = (*seed_routes, *known_routes)
        self._reference_solutions.extend((baseline_routes, *seed_routes))
        candidate_groups: list[tuple[RouteCandidate, ...]] = []
        state_groups: list[tuple[Engineer, tuple[_GraphState, ...]]] = []
        for engineer in self._ordered_engineers(planning_input):
            pool = tuple(
                job for job in planning_input.jobs if PlanningRules.eligible(engineer, job)
            )
            states = self._cached_candidate_states(
                engineer,
                pool,
                layers_by_request,
                planning_input.calculation_cutoff_at,
                job_positions,
            )
            state_groups.append((engineer, states))
            candidates = self._route_candidates(
                engineer,
                states,
                jobs_by_id,
                job_positions,
            )
            reference_paths = (
                baseline_routes.get(engineer.id, ()),
                *(routes.get(engineer.id, ()) for routes in seed_routes),
            )
            for reference_path in reference_paths:
                if reference_path and all(
                    candidate.request_ids != reference_path for candidate in candidates
                ):
                    candidates = (
                        *candidates,
                        self._candidate_from_path(
                            engineer,
                            reference_path,
                            jobs_by_id,
                            layers_by_request,
                            job_positions,
                        ),
                    )
            candidate_groups.append(candidates)

        self._add_exact_sequential_reference(
            candidate_groups,
            state_groups,
            planning_input.jobs,
            jobs_by_id,
            layers_by_request,
            job_positions,
            planning_input.calculation_cutoff_at,
        )
        selection = self._select_routes(
            candidate_groups,
            state_groups,
            planning_input.jobs,
            jobs_by_id,
            layers_by_request,
            job_positions,
            planning_input.calculation_cutoff_at,
            planning_input.mode,
        )
        return {
            engineer_id: request_ids
            for engineer_id, request_ids in selection.routes.items()
            if request_ids
        }

    def best_route(
        self,
        engineer: Engineer,
        jobs: Sequence[Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_at: datetime,
        job_positions: dict[uuid.UUID, int],
    ) -> tuple[tuple[uuid.UUID, ...], int, int]:
        """Точный лучший маршрут одного инженера из переданного пула заявок.

        Лучший — по `(priority_score, число заявок, -дорога)`; повторный пул в рамках
        одного экземпляра берётся из кэша графов.

        Returns:
            Порядок заявок, суммарный priority score и дорога в минутах.
        """

        states = self._cached_candidate_states(
            engineer, jobs, layers_by_request, cutoff_at, job_positions
        )
        best = max(
            states,
            key=lambda state: (state.priority_score, len(state.path), -state.travel_minutes),
        )
        return best.path, best.priority_score, best.travel_minutes

    def _select_routes(
        self,
        candidate_groups: list[tuple[RouteCandidate, ...]],
        state_groups: list[tuple[Engineer, tuple[_GraphState, ...]]],
        jobs: Sequence[Job],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        job_positions: dict[uuid.UUID, int],
        cutoff_at: datetime,
        mode: DistributionMode,
    ) -> CandidateSelectionResult:
        generation_mode = (
            DistributionMode.MIN_ENGINEERS if mode == DistributionMode.BALANCED else mode
        )
        selection = self._run_selector(candidate_groups, generation_mode)
        for _ in range(cfg.algorithm.route_candidate_improvement_rounds):
            changed = self._add_exact_best_responses(
                candidate_groups,
                state_groups,
                selection,
                jobs,
                jobs_by_id,
                layers_by_request,
                job_positions,
                cutoff_at,
            )
            if not changed:
                break
            selection = self._run_selector(candidate_groups, generation_mode, (selection.routes,))
        if generation_mode != mode:
            return self._run_selector(candidate_groups, mode, (selection.routes,))
        return selection

    def _run_selector(
        self,
        candidate_groups: Sequence[tuple[RouteCandidate, ...]],
        mode: DistributionMode,
        known_solutions: Sequence[dict[uuid.UUID, tuple[uuid.UUID, ...]]] = (),
    ) -> CandidateSelectionResult:
        """Запускает selector, передавая ему известные полные решения как incumbents.

        Seed-решения (baseline, greedy, priority append) и переданные решения переводятся
        в колонки групп; решение, для которого в группах нет колонки, пропускается.
        """

        started_at = self._diagnostics.start_selection() if self._diagnostics is not None else 0
        groups = tuple(candidate_groups)
        columns_by_engineer = {
            group[0].engineer_id: {candidate.request_ids: candidate for candidate in group}
            for group in groups
        }
        incumbents: list[tuple[RouteCandidate, ...]] = []
        for solution in (*self._reference_solutions, *known_solutions):
            columns = tuple(
                columns_by_engineer[engineer_id].get(solution.get(engineer_id, ()))
                for engineer_id in columns_by_engineer
            )
            if all(column is not None for column in columns):
                incumbents.append(tuple(column for column in columns if column is not None))
        selection = self._selector.select(groups, mode, incumbents)
        if self._diagnostics is not None:
            self._diagnostics.finish_selection(
                started_at=started_at,
                candidate_routes_count=sum(len(group) for group in candidate_groups),
                visited_nodes_count=selection.visited_nodes_count,
                conflict_prunes_count=selection.conflict_prunes_count,
                bound_prunes_count=selection.bound_prunes_count,
            )
        return selection

    def _add_exact_sequential_reference(
        self,
        candidate_groups: list[tuple[RouteCandidate, ...]],
        state_groups: list[tuple[Engineer, tuple[_GraphState, ...]]],
        jobs: Sequence[Job],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        job_positions: dict[uuid.UUID, int],
        cutoff_at: datetime,
    ) -> None:
        used_mask = 0
        for group_index, (engineer, states) in enumerate(state_groups):
            if group_index:
                pool = tuple(
                    job
                    for job in jobs
                    if not (used_mask & (1 << job_positions[job.id]))
                    and PlanningRules.eligible(engineer, job)
                )
                states = self._cached_candidate_states(
                    engineer,
                    pool,
                    layers_by_request,
                    cutoff_at,
                    job_positions,
                )
            candidates = list(candidate_groups[group_index])
            seen_masks = {candidate.request_mask for candidate in candidates}
            state = states[0]
            request_mask = self._request_mask(state.path, job_positions)
            self._append_route_candidate(
                candidates,
                seen_masks,
                state,
                engineer,
                jobs_by_id,
                job_positions,
            )
            used_mask |= request_mask
            candidate_groups[group_index] = tuple(candidates)

    def _add_exact_best_responses(
        self,
        candidate_groups: list[tuple[RouteCandidate, ...]],
        state_groups: list[tuple[Engineer, tuple[_GraphState, ...]]],
        selection: CandidateSelectionResult,
        jobs: Sequence[Job],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        job_positions: dict[uuid.UUID, int],
        cutoff_at: datetime,
    ) -> bool:
        selected_masks = {
            engineer_id: self._request_mask(request_ids, job_positions)
            for engineer_id, request_ids in selection.routes.items()
        }
        changed = False
        for group_index, (engineer, _) in enumerate(state_groups):
            blocked_mask = 0
            for engineer_id, request_mask in selected_masks.items():
                if engineer_id != engineer.id:
                    blocked_mask |= request_mask
            candidates = list(candidate_groups[group_index])
            seen_masks = {candidate.request_mask for candidate in candidates}
            pool = tuple(
                job
                for job in jobs
                if not (blocked_mask & (1 << job_positions[job.id]))
                and PlanningRules.eligible(engineer, job)
            )
            states = self._cached_candidate_states(
                engineer,
                pool,
                layers_by_request,
                cutoff_at,
                job_positions,
            )
            added_count = 0
            for state in states:
                request_mask = self._request_mask(state.path, job_positions)
                if request_mask in seen_masks:
                    continue
                self._append_route_candidate(
                    candidates,
                    seen_masks,
                    state,
                    engineer,
                    jobs_by_id,
                    job_positions,
                )
                added_count += 1
                changed = True
                if added_count >= cfg.algorithm.route_candidates_per_improvement_round:
                    break
            candidate_groups[group_index] = tuple(candidates)
        return changed

    def _cached_candidate_states(
        self,
        engineer: Engineer,
        jobs: Sequence[Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_at: datetime,
        job_positions: dict[uuid.UUID, int],
    ) -> tuple[_GraphState, ...]:
        allowed_mask = self._request_mask((job.id for job in jobs), job_positions)
        cache_key = (engineer.id, allowed_mask)
        cached = self._state_cache.get(cache_key)
        if cached is not None:
            self._cache_hits_count += 1
            return cached
        self._cache_misses_count += 1
        states = self._candidate_states(engineer, jobs, layers_by_request, cutoff_at)
        self._state_cache[cache_key] = states
        return states

    def _candidate_states(
        self,
        engineer: Engineer,
        jobs: Sequence[Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_at: datetime,
    ) -> tuple[_GraphState, ...]:
        graph_run_id = self._diagnostics.start_graph_run() if self._diagnostics is not None else 0
        cutoff_us = self.timestamp_us(cutoff_at)
        shift_end_us = self.timestamp_us(engineer.shift_end)
        states = [
            _GraphState(
                last_int=engineer.id.int,
                finish_us=self.timestamp_us(max(engineer.available_from, cutoff_at)),
                travel_minutes=0,
                priority_score=0,
                path=(),
                path_ints=(),
            )
        ]
        jobs_by_layer: dict[tuple[datetime, datetime], list[Job]] = {}
        for job in jobs:
            layer = layers_by_request[job.id]
            jobs_by_layer.setdefault((layer.window_start, layer.window_end), []).append(job)

        for layer_key in sorted(jobs_by_layer):
            layer_started_at = (
                self._diagnostics.start_layer() if self._diagnostics is not None else 0
            )
            bucket = sorted(
                jobs_by_layer[layer_key],
                key=lambda job: (
                    not job.is_emergency,
                    job.priority,
                    job.latest_start_at,
                    str(job.id),
                ),
            )
            counts = _LayerSearchCounts(input_states_count=len(states))
            all_states = self._expand_layer(
                engineer, bucket, states, layers_by_request, cutoff_us, shift_end_us, counts
            )
            states = self._layer_frontier(all_states)
            if self._diagnostics is not None:
                self._diagnostics.add_layer(
                    started_at=layer_started_at,
                    engineer_id=engineer.id,
                    graph_run_id=graph_run_id,
                    window_start=layer_key[0],
                    window_end=layer_key[1],
                    jobs_count=len(bucket),
                    input_states_count=counts.input_states_count,
                    transition_attempts_count=counts.transition_attempts_count,
                    feasible_transitions_count=counts.feasible_transitions_count,
                    rejected_by_time_count=counts.rejected_by_time_count,
                    rejected_by_pareto_count=counts.rejected_by_pareto_count,
                    pruned_by_pareto_count=counts.pruned_by_pareto_count,
                    candidates_count=len(all_states),
                    output_states_count=len(states),
                )

        return tuple(sorted(states, key=self._state_key, reverse=True))

    def _expand_layer(
        self,
        engineer: Engineer,
        bucket: Sequence[Job],
        states: Sequence[_GraphState],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_us: int,
        shift_end_us: int,
        counts: _LayerSearchCounts,
    ) -> list[_GraphState]:
        """Перебирает заявки одного слоя от входных состояний.

        Returns:
            Входные состояния и все недоминируемые внутри слоя продолжения.
        """

        transitions = [
            (
                index,
                1 << index,
                job,
                job.id.int,
                layers_by_request[job.id],
                self.timestamp_us(job.release_at),
                self.timestamp_us(job.latest_start_at),
                job.service_minutes * 60_000_000,
                PlanningRules.priority_score(job.priority),
            )
            for index, job in enumerate(bucket)
        ]
        # Время перехода «последняя точка → заявка слоя» заполняется лениво: к матрице
        # идут ровно те пары, которые перебор действительно проверяет.
        travel_rows: dict[int, list[int | None]] = {}
        layer_latest_us = max(transition[6] for transition in transitions)
        all_states = list(states)
        transition_attempts_count = 0
        feasible_transitions_count = 0
        rejected_by_time_count = 0
        rejected_by_pareto_count = 0
        pruned_by_pareto_count = 0
        frontier = [(0, state) for state in states]
        for _ in range(len(bucket)):
            labels: dict[tuple[int, int, int, int], list[tuple[int, _GraphState]]] = {}
            for mask, state in frontier:
                # Начало не раньше finish, поэтому состояние, закончившее позже крайнего
                # начала любой заявки слоя, никуда не переходит.
                if state.finish_us > layer_latest_us:
                    skipped_count = len(bucket) - mask.bit_count()
                    transition_attempts_count += skipped_count
                    rejected_by_time_count += skipped_count
                    continue
                row = travel_rows.get(state.last_int)
                if row is None:
                    row = travel_rows[state.last_int] = [None] * len(bucket)
                last_id = state.path[-1] if state.path else engineer.id
                for (
                    index,
                    bit,
                    job,
                    job_int,
                    layer,
                    release_us,
                    latest_us,
                    service_us,
                    score,
                ) in transitions:
                    if mask & bit:
                        continue
                    transition_attempts_count += 1
                    if state.finish_us > latest_us:
                        rejected_by_time_count += 1
                        continue
                    travel = row[index]
                    if travel is None:
                        travel = row[index] = self._cached_travel_minutes(
                            layer, engineer, last_id, job.id
                        )
                    start = max(state.finish_us + travel * 60_000_000, release_us, cutoff_us)
                    finish = start + service_us
                    if start > latest_us or finish > shift_end_us:
                        rejected_by_time_count += 1
                        continue
                    feasible_transitions_count += 1
                    path_ints = (*state.path_ints, job_int)
                    priority_score = state.priority_score + score
                    group = labels.setdefault(
                        (mask | bit, job_int, len(path_ints), priority_score), []
                    )
                    travel_minutes = state.travel_minutes + travel
                    accepted, pruned_count = self._add_pareto(
                        group, finish, travel_minutes, path_ints
                    )
                    if not accepted:
                        rejected_by_pareto_count += 1
                        continue
                    pruned_by_pareto_count += pruned_count
                    group.append(
                        (
                            mask | bit,
                            _GraphState(
                                last_int=job_int,
                                finish_us=finish,
                                travel_minutes=travel_minutes,
                                priority_score=priority_score,
                                path=(*state.path, job.id),
                                path_ints=path_ints,
                            ),
                        )
                    )
            frontier = [item for group in labels.values() for item in group]
            all_states.extend(state for _, state in frontier)
            if not frontier:
                break
        counts.transition_attempts_count = transition_attempts_count
        counts.feasible_transitions_count = feasible_transitions_count
        counts.rejected_by_time_count = rejected_by_time_count
        counts.rejected_by_pareto_count = rejected_by_pareto_count
        counts.pruned_by_pareto_count = pruned_by_pareto_count
        return all_states

    def _route_candidates(
        self,
        engineer: Engineer,
        states: Sequence[_GraphState],
        jobs_by_id: dict[uuid.UUID, Job],
        job_positions: dict[uuid.UUID, int],
        limit: int | None = None,
    ) -> tuple[RouteCandidate, ...]:
        candidates: list[RouteCandidate] = []
        seen_masks: set[int] = set()
        candidate_limit = limit or cfg.algorithm.route_candidates_per_engineer
        preferred_count = max(1, candidate_limit // 2)
        for state in states[:preferred_count]:
            self._append_route_candidate(
                candidates,
                seen_masks,
                state,
                engineer,
                jobs_by_id,
                job_positions,
            )
        seen_profiles: set[tuple[int, int, int]] = set()
        for state in states:
            emergency_mask = self._request_mask(
                (request_id for request_id in state.path if jobs_by_id[request_id].is_emergency),
                job_positions,
            )
            priority_two_count = sum(
                jobs_by_id[request_id].priority == 2 for request_id in state.path
            )
            profile = (emergency_mask, priority_two_count, len(state.path))
            if profile in seen_profiles:
                continue
            seen_profiles.add(profile)
            self._append_route_candidate(
                candidates,
                seen_masks,
                state,
                engineer,
                jobs_by_id,
                job_positions,
            )
            if len(candidates) >= candidate_limit:
                break
        if not any(not candidate.request_ids for candidate in candidates):
            candidates.append(
                RouteCandidate(
                    engineer_id=engineer.id,
                    request_ids=(),
                    request_mask=0,
                    priority_score=0,
                    travel_minutes=0,
                    service_minutes=0,
                    history_service_minutes=engineer.history_service_minutes,
                )
            )
        return tuple(candidates)

    def _append_route_candidate(
        self,
        candidates: list[RouteCandidate],
        seen_masks: set[int],
        state: _GraphState,
        engineer: Engineer,
        jobs_by_id: dict[uuid.UUID, Job],
        job_positions: dict[uuid.UUID, int],
    ) -> None:
        request_mask = self._request_mask(state.path, job_positions)
        if request_mask in seen_masks:
            return
        seen_masks.add(request_mask)
        candidates.append(
            RouteCandidate(
                engineer_id=engineer.id,
                request_ids=state.path,
                request_mask=request_mask,
                priority_score=state.priority_score,
                travel_minutes=state.travel_minutes,
                service_minutes=sum(
                    jobs_by_id[request_id].service_minutes for request_id in state.path
                ),
                history_service_minutes=engineer.history_service_minutes,
            )
        )

    def _candidate_from_path(
        self,
        engineer: Engineer,
        path: tuple[uuid.UUID, ...],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        job_positions: dict[uuid.UUID, int],
    ) -> RouteCandidate:
        previous_id = engineer.id
        travel_minutes = 0
        for request_id in path:
            travel_minutes += self.travel_minutes(
                layers_by_request[request_id], engineer, previous_id, request_id
            )
            previous_id = request_id
        return RouteCandidate(
            engineer_id=engineer.id,
            request_ids=path,
            request_mask=self._request_mask(path, job_positions),
            priority_score=sum(
                PlanningRules.priority_score(jobs_by_id[request_id].priority) for request_id in path
            ),
            travel_minutes=travel_minutes,
            service_minutes=sum(jobs_by_id[request_id].service_minutes for request_id in path),
            history_service_minutes=engineer.history_service_minutes,
        )

    @staticmethod
    def _request_mask(request_ids: Iterable[uuid.UUID], job_positions: dict[uuid.UUID, int]) -> int:
        mask = 0
        for request_id in request_ids:
            mask |= 1 << job_positions[request_id]
        return mask

    def _ordered_engineers(self, planning_input: InitialPlanningInput) -> list[Engineer]:
        available = [engineer for engineer in planning_input.engineers if engineer.is_available]
        pool_sizes = {
            engineer.id: sum(PlanningRules.eligible(engineer, job) for job in planning_input.jobs)
            for engineer in available
        }
        if planning_input.mode == DistributionMode.MIN_ENGINEERS:
            return sorted(
                available,
                key=lambda engineer: (-pool_sizes[engineer.id], str(engineer.id)),
            )
        return sorted(
            available,
            key=lambda engineer: (pool_sizes[engineer.id], str(engineer.id)),
        )

    @staticmethod
    def _add_pareto(
        labels: list[tuple[int, _GraphState]],
        finish_us: int,
        travel_minutes: int,
        path_ints: tuple[int, ...],
    ) -> tuple[bool, int]:
        """Проверяет кандидата против меток одной сигнатуры и удаляет доминируемые им.

        В одной сигнатуре совпадают маска, последняя точка, число заявок и score, поэтому
        при равных finish и travel полный ключ состояния сводится к порядку пути.

        Returns:
            Принят ли кандидат и сколько меток он вытеснил (+1 за себя, как в диагностике).
        """

        for _, state in labels:
            if (
                state.finish_us <= finish_us
                and state.travel_minutes <= travel_minutes
                and (
                    state.finish_us < finish_us
                    or state.travel_minutes < travel_minutes
                    or state.path_ints >= path_ints
                )
            ):
                return False, 0
        previous_count = len(labels)
        labels[:] = [
            (mask, state)
            for mask, state in labels
            if not (
                finish_us <= state.finish_us
                and travel_minutes <= state.travel_minutes
                and (
                    finish_us < state.finish_us
                    or travel_minutes < state.travel_minutes
                    or path_ints > state.path_ints
                )
            )
        ]
        return True, previous_count - len(labels) + 1

    def _layer_frontier(self, candidates: Sequence[_GraphState]) -> list[_GraphState]:
        """Оставляет по каждой последней точке состояния, не доминируемые по
        `(priority_score, count, finish, travel)`.

        Кандидаты идут по убыванию полного ключа, поэтому поздний кандидат не может
        доминировать над уже принятым. Достаточно проверить, есть ли среди принятых
        состояний с не меньшими score и числом заявок то, что закончилось не позже и с
        не большей дорогой. Внутри класса `(score, count)` принятые состояния образуют
        лестницу: finish строго растёт, travel строго падает, — поэтому проверка сводится
        к бинарному поиску.
        """

        by_last: dict[
            int,
            tuple[list[_GraphState], dict[tuple[int, int], tuple[list[int], list[int]]]],
        ] = {}
        for candidate in sorted(candidates, key=self._state_key, reverse=True):
            kept, staircases = by_last.setdefault(candidate.last_int, ([], {}))
            count = len(candidate.path)
            score = candidate.priority_score
            finish_us = candidate.finish_us
            travel_minutes = candidate.travel_minutes
            if self._dominated_by_staircases(staircases, score, count, finish_us, travel_minutes):
                continue
            finishes, travels = staircases.setdefault((score, count), ([], []))
            index = bisect_right(finishes, finish_us)
            finishes.insert(index, finish_us)
            travels.insert(index, travel_minutes)
            kept.append(candidate)
        return [state for kept, _ in by_last.values() for state in kept]

    @staticmethod
    def _dominated_by_staircases(
        staircases: dict[tuple[int, int], tuple[list[int], list[int]]],
        score: int,
        count: int,
        finish_us: int,
        travel_minutes: int,
    ) -> bool:
        """Есть ли принятое состояние с не меньшими score и числом заявок, закончившее не
        позже и с не большей дорогой."""

        for (class_score, class_count), (finishes, travels) in staircases.items():
            if class_score < score or class_count < count:
                continue
            index = bisect_right(finishes, finish_us)
            if index and travels[index - 1] <= travel_minutes:
                return True
        return False

    @staticmethod
    def _state_key(state: _GraphState) -> tuple[int, int, int, int, tuple[int, ...]]:
        return (
            state.priority_score,
            len(state.path),
            -state.travel_minutes,
            -(state.finish_us // 1_000_000),
            state.path_ints,
        )

    @staticmethod
    def timestamp_us(value: datetime) -> int:
        """Переводит наивное datetime в целые микросекунды без потери точности."""

        seconds = value.toordinal() * 86_400 + value.hour * 3_600 + value.minute * 60
        return (seconds + value.second) * 1_000_000 + value.microsecond

    def _cached_travel_minutes(
        self,
        layer: PlanningLayer,
        engineer: Engineer,
        from_id: uuid.UUID,
        to_id: uuid.UUID,
    ) -> int:
        """Время перехода с кэшем на время одного расчёта: слой задан целевой заявкой."""

        key = (engineer.vehicle_type.value, from_id, to_id)
        cached = self._travel_cache.get(key)
        if cached is None:
            cached = self.travel_minutes(layer, engineer, from_id, to_id)
            self._travel_cache[key] = cached
        return cached

    @staticmethod
    def travel_minutes(
        layer: PlanningLayer,
        engineer: Engineer,
        from_id: uuid.UUID,
        to_id: uuid.UUID,
    ) -> int:
        """Время перехода по матрице слоя целевой заявки и транспорта инженера.

        Недостижимая пара получает время заведомо больше любого рабочего дня: такой
        переход отсекается обычной проверкой окна и смены, а финальный маршрут всё равно
        строит материализация, которая видит `None` явно.
        """

        matrices = [
            item.travel_matrix
            for item in layer.matrices
            if item.vehicle_type == engineer.vehicle_type
        ]
        if len(matrices) != 1:
            raise AlgorithmInputError(
                f"Для слоя заявки {to_id} нет единственной матрицы "
                f"транспорта {engineer.vehicle_type}"
            )
        try:
            minutes = matrices[0].minutes(from_id, to_id)
        except (KeyError, IndexError) as exc:
            raise AlgorithmInputError(
                f"Матрица слоя не покрывает переход {from_id} -> {to_id}"
            ) from exc
        unreachable_minutes = 7 * 24 * 60
        return unreachable_minutes if minutes is None else minutes
