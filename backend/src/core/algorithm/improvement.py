import random
import uuid
from collections.abc import Callable, Iterable
from decimal import Decimal

from src.core.algorithm.distribution import DistributionPlanner
from src.core.algorithm.dto import (
    AdaptiveSearchResult,
    AdaptiveSearchStats,
    CandidateSelectionResult,
    EjectionSearchResult,
    Engineer,
    ImprovementContext,
    InitialPlanningInput,
    Job,
    RouteCandidate,
)
from src.core.algorithm.enums import DestroyOperator, DistributionMode


class RouteCandidateArchive:
    """Хранит лучший известный порядок для каждой пары инженер + набор заявок."""

    def __init__(
        self,
        engineers: tuple[Engineer, ...],
        candidate_groups: tuple[tuple[RouteCandidate, ...], ...],
    ) -> None:
        candidates_by_engineer = {
            group[0].engineer_id: {candidate.request_mask: candidate for candidate in group}
            for group in candidate_groups
        }
        self._engineer_ids = tuple(engineer.id for engineer in engineers)
        self._candidates_by_engineer = {
            engineer_id: candidates_by_engineer[engineer_id] for engineer_id in self._engineer_ids
        }

    def add(self, candidate: RouteCandidate) -> bool:
        candidates = self._candidates_by_engineer[candidate.engineer_id]
        current = candidates.get(candidate.request_mask)
        if current is not None and self._candidate_key(current) >= self._candidate_key(candidate):
            return False
        candidates[candidate.request_mask] = candidate
        return True

    def groups(self) -> tuple[tuple[RouteCandidate, ...], ...]:
        return tuple(
            tuple(
                sorted(
                    self._candidates_by_engineer[engineer_id].values(),
                    key=self._candidate_key,
                    reverse=True,
                )
            )
            for engineer_id in self._engineer_ids
        )

    @staticmethod
    def _candidate_key(candidate: RouteCandidate) -> tuple[int, int, int, tuple[int, ...]]:
        return (
            candidate.priority_score,
            len(candidate.request_ids),
            -candidate.travel_minutes,
            tuple(request_id.int for request_id in candidate.request_ids),
        )


class GreedyEjectionSearch:
    """Строит восстановленные решения после временного удаления одной заявки."""

    def __init__(self, planner: DistributionPlanner) -> None:
        self._planner = planner

    def generate(
        self,
        planning_input: InitialPlanningInput,
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
    ) -> EjectionSearchResult:
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        assigned_ids = tuple(request_id for route in routes.values() for request_id in route)
        assigned_set = set(assigned_ids)
        unassigned_jobs = [job for job in planning_input.jobs if job.id not in assigned_set]
        solutions: list[dict[uuid.UUID, tuple[uuid.UUID, ...]]] = []
        seen: set[tuple[tuple[int, tuple[int, ...]], ...]] = set()
        for removed_id in assigned_ids:
            candidate_routes = {
                engineer.id: tuple(
                    request_id
                    for request_id in routes.get(engineer.id, ())
                    if request_id != removed_id
                )
                for engineer in planning_input.engineers
            }
            self._planner.complete(
                [*unassigned_jobs, jobs_by_id[removed_id]],
                candidate_routes,
                planning_input,
            )
            signature = tuple(
                (
                    engineer_id.int,
                    tuple(request_id.int for request_id in request_ids),
                )
                for engineer_id, request_ids in sorted(
                    candidate_routes.items(), key=lambda item: item[0].int
                )
            )
            if signature in seen:
                continue
            seen.add(signature)
            solutions.append(
                {
                    engineer_id: request_ids
                    for engineer_id, request_ids in candidate_routes.items()
                    if request_ids
                }
            )
        return EjectionSearchResult(
            solutions=tuple(solutions),
            attempts_count=len(assigned_ids),
        )


class AdaptiveRouteImprover:
    """Детерминированный ALNS, восстанавливающий окрестности точным графом."""

    def __init__(
        self,
        *,
        iterations: int,
        cluster_fraction: float,
        random_seed: int,
    ) -> None:
        self._iterations = iterations
        self._cluster_fraction = cluster_fraction
        self._random = random.Random(random_seed)
        self._weights = dict.fromkeys(DestroyOperator, 1.0)
        self._uses = dict.fromkeys(DestroyOperator, 0)

    def improve(
        self,
        context: ImprovementContext,
        candidate_groups: tuple[tuple[RouteCandidate, ...], ...],
        initial_selection: CandidateSelectionResult,
        generate: Callable[[Engineer, int], tuple[RouteCandidate, ...]],
        select: Callable[
            [tuple[tuple[RouteCandidate, ...], ...], DistributionMode],
            CandidateSelectionResult,
        ],
        cache_counts: Callable[[], tuple[int, int]],
    ) -> AdaptiveSearchResult:
        archive = RouteCandidateArchive(context.engineers, candidate_groups)
        best = initial_selection
        improvements_count = 0
        generated_candidates_count = 0
        iterations_count = self._iterations if context.engineers and context.jobs else 0
        for _ in range(iterations_count):
            operator = self._choose_operator()
            self._uses[operator] += 1
            neighborhoods = self._neighborhoods(context, best, operator)
            archive_changed, generated_count = self._repair_neighborhood(
                neighborhoods,
                archive,
                generate,
            )
            generated_candidates_count += generated_count
            if not archive_changed:
                self._weights[operator] = max(0.1, self._weights[operator] * 0.9)
                continue
            candidate = select(archive.groups(), context.mode)
            if candidate.quality_key > best.quality_key:
                best = candidate
                improvements_count += 1
                self._weights[operator] += 3.0
            else:
                self._weights[operator] += 0.25
        cache_hits_count, cache_misses_count = cache_counts()
        return AdaptiveSearchResult(
            selection=best,
            candidate_groups=archive.groups(),
            stats=AdaptiveSearchStats(
                iterations_count=iterations_count,
                improvements_count=improvements_count,
                generated_candidates_count=generated_candidates_count,
                cache_hits_count=cache_hits_count,
                cache_misses_count=cache_misses_count,
                operator_uses=tuple(
                    (operator, self._uses[operator]) for operator in DestroyOperator
                ),
            ),
        )

    @staticmethod
    def _repair_neighborhood(
        neighborhoods: tuple[tuple[Engineer, int], ...],
        archive: RouteCandidateArchive,
        generate: Callable[[Engineer, int], tuple[RouteCandidate, ...]],
    ) -> tuple[bool, int]:
        orders = (neighborhoods, tuple(reversed(neighborhoods)))
        archive_changed = False
        generated_count = 0
        for order in orders:
            reserved_mask = 0
            for engineer, allowed_mask in order:
                generated = generate(engineer, allowed_mask & ~reserved_mask)
                generated_count += len(generated)
                for candidate in generated:
                    archive_changed = archive.add(candidate) or archive_changed
                if generated:
                    reserved_mask |= generated[0].request_mask
        return archive_changed, generated_count

    def _choose_operator(self) -> DestroyOperator:
        threshold = self._random.random() * sum(self._weights.values())
        cumulative = 0.0
        for operator in DestroyOperator:
            cumulative += self._weights[operator]
            if cumulative >= threshold:
                return operator
        return tuple(DestroyOperator)[-1]

    def _neighborhoods(
        self,
        context: ImprovementContext,
        selection: CandidateSelectionResult,
        operator: DestroyOperator,
    ) -> tuple[tuple[Engineer, int], ...]:
        route_masks = {
            engineer.id: self._request_mask(
                selection.routes.get(engineer.id, ()), context.job_positions
            )
            for engineer in context.engineers
        }
        assigned_mask = 0
        for route_mask in route_masks.values():
            assigned_mask |= route_mask
        all_jobs_mask = (1 << len(context.jobs)) - 1
        unassigned_mask = all_jobs_mask ^ assigned_mask
        if operator == DestroyOperator.SINGLE_ENGINEER:
            engineer = self._random.choice(context.engineers)
            return ((engineer, route_masks[engineer.id] | unassigned_mask),)
        if operator == DestroyOperator.ENGINEER_PAIR:
            selected_engineers = self._random.sample(
                context.engineers,
                k=min(2, len(context.engineers)),
            )
            repair_mask = unassigned_mask
            for engineer in selected_engineers:
                repair_mask |= route_masks[engineer.id]
            return tuple((engineer, repair_mask) for engineer in selected_engineers)
        destroy_mask = self._destroy_mask(context, operator)
        return tuple(
            (
                engineer,
                route_masks[engineer.id] | unassigned_mask | destroy_mask,
            )
            for engineer in context.engineers
        )

    def _destroy_mask(
        self,
        context: ImprovementContext,
        operator: DestroyOperator,
    ) -> int:
        if operator == DestroyOperator.TIME_WINDOW:
            windows = sorted({(job.release_at, job.latest_start_at) for job in context.jobs})
            selected_window = self._random.choice(windows)
            selected_jobs = [
                job
                for job in context.jobs
                if (job.release_at, job.latest_start_at) == selected_window
            ]
        else:
            pivot = self._random.choice(context.jobs)
            cluster_size = max(1, round(len(context.jobs) * self._cluster_fraction))
            selected_jobs = sorted(
                context.jobs,
                key=lambda job: self._distance_squared(pivot, job),
            )[:cluster_size]
        return self._request_mask(
            (job.id for job in selected_jobs),
            context.job_positions,
        )

    @staticmethod
    def _distance_squared(left: Job, right: Job) -> Decimal:
        latitude_delta = left.latitude - right.latitude
        longitude_delta = left.longitude - right.longitude
        return latitude_delta * latitude_delta + longitude_delta * longitude_delta

    @staticmethod
    def _request_mask(
        request_ids: Iterable[uuid.UUID],
        job_positions: dict[uuid.UUID, int],
    ) -> int:
        mask = 0
        for request_id in request_ids:
            mask |= 1 << job_positions[request_id]
        return mask
