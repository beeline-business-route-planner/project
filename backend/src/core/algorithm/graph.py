import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from src.config import cfg
from src.core.algorithm.diagnostics import AlgorithmDiagnostics
from src.core.algorithm.distribution import DistributionPlanner
from src.core.algorithm.dto import (
    CandidateSelectionResult,
    Engineer,
    ImprovementContext,
    InitialPlanningInput,
    Job,
    PlanningLayer,
    RouteCandidate,
)
from src.core.algorithm.enums import DistributionMode
from src.core.algorithm.exc import AlgorithmInputError
from src.core.algorithm.improvement import AdaptiveRouteImprover, GreedyEjectionSearch
from src.core.algorithm.selection import GlobalRouteSelector


@dataclass(frozen=True)
class _GraphState:
    """Достижимое состояние маршрута после нуля или нескольких заявок слоя."""

    mask: int
    last_id: uuid.UUID
    finish: datetime
    travel_minutes: int
    priority_score: int
    path: tuple[uuid.UUID, ...]


class LayeredGraphPlanner:
    """Планирует инженеров точным графом состояний по временным окнам заявок."""

    def __init__(
        self,
        *,
        greedy_completion: bool,
        adaptive_improvement: bool,
        diagnostics: AlgorithmDiagnostics | None = None,
    ) -> None:
        self._distribution = DistributionPlanner()
        self._selector = GlobalRouteSelector()
        self._greedy_completion = greedy_completion
        self._adaptive_improvement = adaptive_improvement
        self._diagnostics = diagnostics
        self._state_cache: dict[tuple[uuid.UUID, int], tuple[_GraphState, ...]] = {}
        self._cache_hits_count = 0
        self._cache_misses_count = 0

    def assign(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        self._state_cache.clear()
        self._cache_hits_count = 0
        self._cache_misses_count = 0
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        layers_by_request = self._distribution.index_layers(planning_input.layers, jobs_by_id)
        job_positions = {job.id: position for position, job in enumerate(planning_input.jobs)}
        baseline_routes = self._distribution.assign_baseline(planning_input)
        seed_inputs = tuple(replace(planning_input, mode=mode) for mode in DistributionMode)
        seed_routes = tuple(
            routes
            for seed_input in seed_inputs
            for routes in (
                self._distribution.assign(seed_input),
                self._distribution.assign_priority_append_seed(seed_input),
            )
        )
        candidate_groups: list[tuple[RouteCandidate, ...]] = []
        state_groups: list[tuple[Engineer, tuple[_GraphState, ...]]] = []
        for engineer in self._ordered_engineers(planning_input):
            pool = tuple(
                job for job in planning_input.jobs if self._distribution.eligible(engineer, job)
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
        if self._adaptive_improvement:
            selection, candidate_groups = self._improve_by_ejection(
                selection,
                candidate_groups,
                state_groups,
                planning_input,
                jobs_by_id,
                layers_by_request,
                job_positions,
            )
            selection, candidate_groups = self._improve_adaptively(
                selection,
                candidate_groups,
                state_groups,
                planning_input,
                jobs_by_id,
                layers_by_request,
                job_positions,
            )
        routes = {
            engineer.id: selection.routes.get(engineer.id, ())
            for engineer in planning_input.engineers
        }
        remaining_ids = {job.id for job in planning_input.jobs} - {
            request_id for request_ids in routes.values() for request_id in request_ids
        }

        if self._greedy_completion and remaining_ids:
            self._distribution.complete(
                [jobs_by_id[job_id] for job_id in remaining_ids],
                routes,
                planning_input,
            )
        return {
            engineer_id: request_ids for engineer_id, request_ids in routes.items() if request_ids
        }

    def _improve_by_ejection(
        self,
        selection: CandidateSelectionResult,
        candidate_groups: list[tuple[RouteCandidate, ...]],
        state_groups: list[tuple[Engineer, tuple[_GraphState, ...]]],
        planning_input: InitialPlanningInput,
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        job_positions: dict[uuid.UUID, int],
    ) -> tuple[CandidateSelectionResult, list[tuple[RouteCandidate, ...]]]:
        search_seeds = [(planning_input, selection)]
        if planning_input.mode == DistributionMode.BALANCED:
            search_seeds.append(
                (
                    replace(planning_input, mode=DistributionMode.MIN_ENGINEERS),
                    self._run_selector(candidate_groups, DistributionMode.MIN_ENGINEERS),
                )
            )
        generated_searches = tuple(
            GreedyEjectionSearch(self._distribution).generate(
                search_input,
                search_selection.routes,
            )
            for search_input, search_selection in search_seeds
        )
        generated_solutions = {
            tuple(sorted(solution.items(), key=lambda item: item[0].int)): solution
            for generated in generated_searches
            for solution in generated.solutions
        }
        group_indexes = {engineer.id: index for index, (engineer, _) in enumerate(state_groups)}
        engineers_by_id = {engineer.id: engineer for engineer, _ in state_groups}
        mutable_groups = [list(group) for group in candidate_groups]
        initial_candidates_count = sum(len(group) for group in mutable_groups)
        for solution in generated_solutions.values():
            for engineer_id, path in solution.items():
                group = mutable_groups[group_indexes[engineer_id]]
                if any(candidate.request_ids == path for candidate in group):
                    continue
                group.append(
                    self._candidate_from_path(
                        engineers_by_id[engineer_id],
                        path,
                        jobs_by_id,
                        layers_by_request,
                        job_positions,
                    )
                )
        improved_groups = [tuple(group) for group in mutable_groups]
        improved_selection = self._run_selector(improved_groups, planning_input.mode)
        if self._diagnostics is not None:
            self._diagnostics.record_ejection_search(
                attempts_count=sum(generated.attempts_count for generated in generated_searches),
                unique_solutions_count=len(generated_solutions),
                added_candidates_count=sum(len(group) for group in improved_groups)
                - initial_candidates_count,
                improved=improved_selection.quality_key > selection.quality_key,
            )
        return improved_selection, improved_groups

    def _improve_adaptively(
        self,
        selection: CandidateSelectionResult,
        candidate_groups: list[tuple[RouteCandidate, ...]],
        state_groups: list[tuple[Engineer, tuple[_GraphState, ...]]],
        planning_input: InitialPlanningInput,
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        job_positions: dict[uuid.UUID, int],
    ) -> tuple[CandidateSelectionResult, list[tuple[RouteCandidate, ...]]]:
        engineers = tuple(engineer for engineer, _ in state_groups)
        improver = AdaptiveRouteImprover(
            iterations=cfg.algorithm.alns_iterations,
            cluster_fraction=cfg.algorithm.alns_cluster_fraction,
            random_seed=cfg.algorithm.alns_random_seed,
        )

        def generate(engineer: Engineer, allowed_mask: int) -> tuple[RouteCandidate, ...]:
            pool = tuple(
                job
                for job in planning_input.jobs
                if allowed_mask & (1 << job_positions[job.id])
                and self._distribution.eligible(engineer, job)
            )
            states = self._cached_candidate_states(
                engineer,
                pool,
                layers_by_request,
                planning_input.calculation_cutoff_at,
                job_positions,
            )
            return self._route_candidates(
                engineer,
                states,
                jobs_by_id,
                job_positions,
                limit=cfg.algorithm.alns_candidates_per_repair,
            )

        improved = improver.improve(
            ImprovementContext(
                engineers=engineers,
                jobs=planning_input.jobs,
                job_positions=job_positions,
                mode=planning_input.mode,
            ),
            tuple(candidate_groups),
            selection,
            generate,
            lambda groups, mode: self._run_selector(groups, mode),
            lambda: (self._cache_hits_count, self._cache_misses_count),
        )
        if self._diagnostics is not None:
            self._diagnostics.record_adaptive_search(
                iterations_count=improved.stats.iterations_count,
                improvements_count=improved.stats.improvements_count,
                generated_candidates_count=improved.stats.generated_candidates_count,
                cache_hits_count=improved.stats.cache_hits_count,
                cache_misses_count=improved.stats.cache_misses_count,
                operator_uses=tuple(
                    (operator.value, uses) for operator, uses in improved.stats.operator_uses
                ),
            )
        return improved.selection, list(improved.candidate_groups)

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
            selection = self._run_selector(candidate_groups, generation_mode)
        if generation_mode != mode:
            return self._run_selector(candidate_groups, mode)
        return selection

    def _run_selector(
        self,
        candidate_groups: Sequence[tuple[RouteCandidate, ...]],
        mode: DistributionMode,
    ) -> CandidateSelectionResult:
        started_at = self._diagnostics.start_selection() if self._diagnostics is not None else 0
        selection = self._selector.select(tuple(candidate_groups), mode)
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
                    and self._distribution.eligible(engineer, job)
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
                and self._distribution.eligible(engineer, job)
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
        initial_finish = max(engineer.available_from, cutoff_at)
        states = [
            _GraphState(
                mask=0,
                last_id=engineer.id,
                finish=initial_finish,
                travel_minutes=0,
                priority_score=0,
                path=(),
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
            all_states = list(states)
            input_states_count = len(states)
            transition_attempts_count = 0
            feasible_transitions_count = 0
            rejected_by_time_count = 0
            rejected_by_pareto_count = 0
            pruned_by_pareto_count = 0
            frontier = [
                _GraphState(
                    mask=0,
                    last_id=state.last_id,
                    finish=state.finish,
                    travel_minutes=state.travel_minutes,
                    priority_score=state.priority_score,
                    path=state.path,
                )
                for state in states
            ]
            for _ in range(len(bucket)):
                labels: dict[tuple[int, uuid.UUID, int, int], list[_GraphState]] = {}
                for state in frontier:
                    for position, job in enumerate(bucket):
                        if state.mask & (1 << position):
                            continue
                        transition_attempts_count += 1
                        travel = self._travel_minutes(
                            layers_by_request[job.id],
                            engineer,
                            state.last_id,
                            job.id,
                        )
                        start = max(
                            state.finish + timedelta(minutes=travel),
                            job.release_at,
                            cutoff_at,
                        )
                        finish = start + timedelta(minutes=job.service_minutes)
                        if start > job.latest_start_at or finish > engineer.shift_end:
                            rejected_by_time_count += 1
                            continue
                        feasible_transitions_count += 1
                        candidate = _GraphState(
                            mask=state.mask | (1 << position),
                            last_id=job.id,
                            finish=finish,
                            travel_minutes=state.travel_minutes + travel,
                            priority_score=state.priority_score
                            + self._priority_score(job.priority),
                            path=(*state.path, job.id),
                        )
                        signature = (
                            candidate.mask,
                            candidate.last_id,
                            len(candidate.path),
                            candidate.priority_score,
                        )
                        accepted, pruned_count = self._add_pareto(
                            labels.setdefault(signature, []), candidate
                        )
                        if not accepted:
                            rejected_by_pareto_count += 1
                        pruned_by_pareto_count += pruned_count
                frontier = [state for group in labels.values() for state in group]
                all_states.extend(frontier)
                if not frontier:
                    break
            states = self._layer_frontier(all_states)
            if self._diagnostics is not None:
                self._diagnostics.add_layer(
                    started_at=layer_started_at,
                    engineer_id=engineer.id,
                    graph_run_id=graph_run_id,
                    window_start=layer_key[0],
                    window_end=layer_key[1],
                    jobs_count=len(bucket),
                    input_states_count=input_states_count,
                    transition_attempts_count=transition_attempts_count,
                    feasible_transitions_count=feasible_transitions_count,
                    rejected_by_time_count=rejected_by_time_count,
                    rejected_by_pareto_count=rejected_by_pareto_count,
                    pruned_by_pareto_count=pruned_by_pareto_count,
                    candidates_count=len(all_states),
                    output_states_count=len(states),
                )

        return tuple(sorted(states, key=self._state_key, reverse=True))

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
            travel_minutes += self._travel_minutes(
                layers_by_request[request_id], engineer, previous_id, request_id
            )
            previous_id = request_id
        return RouteCandidate(
            engineer_id=engineer.id,
            request_ids=path,
            request_mask=self._request_mask(path, job_positions),
            priority_score=sum(
                self._priority_score(jobs_by_id[request_id].priority) for request_id in path
            ),
            travel_minutes=travel_minutes,
            service_minutes=sum(jobs_by_id[request_id].service_minutes for request_id in path),
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
            engineer.id: sum(
                self._distribution.eligible(engineer, job) for job in planning_input.jobs
            )
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
    def _add_pareto(labels: list[_GraphState], candidate: _GraphState) -> tuple[bool, int]:
        if any(
            state.finish <= candidate.finish
            and state.travel_minutes <= candidate.travel_minutes
            and (
                state.finish < candidate.finish
                or state.travel_minutes < candidate.travel_minutes
                or LayeredGraphPlanner._state_key(state)
                >= LayeredGraphPlanner._state_key(candidate)
            )
            for state in labels
        ):
            return False, 0
        previous_count = len(labels)
        labels[:] = [
            state
            for state in labels
            if not (
                candidate.finish <= state.finish
                and candidate.travel_minutes <= state.travel_minutes
                and (
                    candidate.finish < state.finish
                    or candidate.travel_minutes < state.travel_minutes
                    or LayeredGraphPlanner._state_key(candidate)
                    > LayeredGraphPlanner._state_key(state)
                )
            )
        ]
        labels.append(candidate)
        return True, previous_count - len(labels) + 1

    def _layer_frontier(self, candidates: Sequence[_GraphState]) -> list[_GraphState]:
        by_last: dict[uuid.UUID, list[_GraphState]] = {}
        for candidate in sorted(candidates, key=self._state_key, reverse=True):
            labels = by_last.setdefault(candidate.last_id, [])
            if any(self._dominates(state, candidate) for state in labels):
                continue
            labels[:] = [state for state in labels if not self._dominates(candidate, state)]
            labels.append(
                _GraphState(
                    mask=0,
                    last_id=candidate.last_id,
                    finish=candidate.finish,
                    travel_minutes=candidate.travel_minutes,
                    priority_score=candidate.priority_score,
                    path=candidate.path,
                )
            )
        return [state for labels in by_last.values() for state in labels]

    @staticmethod
    def _dominates(left: _GraphState, right: _GraphState) -> bool:
        return (
            left.priority_score >= right.priority_score
            and len(left.path) >= len(right.path)
            and left.finish <= right.finish
            and left.travel_minutes <= right.travel_minutes
        )

    @staticmethod
    def _state_key(state: _GraphState) -> tuple[int, int, int, int, tuple[int, ...]]:
        finish_rank = (
            state.finish.toordinal() * 86_400
            + state.finish.hour * 3_600
            + state.finish.minute * 60
            + state.finish.second
        )
        return (
            state.priority_score,
            len(state.path),
            -state.travel_minutes,
            -finish_rank,
            tuple(request_id.int for request_id in state.path),
        )

    @staticmethod
    def _priority_score(priority: int) -> int:
        if priority not in {1, 2, 3}:
            raise AlgorithmInputError("Приоритет заявки должен быть от 1 до 3")
        tier = 4 - priority
        return cfg.algorithm.priority_tier_weight ** (tier - 1)

    @staticmethod
    def _travel_minutes(
        layer: PlanningLayer,
        engineer: Engineer,
        from_id: uuid.UUID,
        to_id: uuid.UUID,
    ) -> int:
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
            return matrices[0].minutes(from_id, to_id)
        except (KeyError, IndexError) as exc:
            raise AlgorithmInputError(
                f"Матрица слоя не покрывает переход {from_id} -> {to_id}"
            ) from exc
