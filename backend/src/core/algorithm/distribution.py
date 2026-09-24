import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from src.core.algorithm.dto import Engineer, InitialPlanningInput, Job, PlanningLayer, Stop
from src.core.algorithm.enums import DistributionMode
from src.core.algorithm.exc import AlgorithmInputError
from src.core.algorithm.materialization import ScheduleMaterializer


@dataclass(frozen=True)
class _InsertionCandidate:
    engineer_id: uuid.UUID
    position: int
    request_ids: tuple[uuid.UUID, ...]
    stops: tuple[Stop, ...]
    added_travel_minutes: int
    projected_service_minutes: int


class DistributionPlanner:
    """Строит маршруты детерминированной вставкой и выполняет greedy completion."""

    def __init__(self) -> None:
        self._materializer = ScheduleMaterializer()

    def assign(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        engineers_by_id = {engineer.id: engineer for engineer in planning_input.engineers}
        layers_by_request = self.index_layers(planning_input.layers, jobs_by_id)
        layer_ranks = self._layer_ranks(planning_input.layers)
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {
            engineer.id: () for engineer in planning_input.engineers
        }
        ordered_jobs = self._ordered_jobs(planning_input.jobs)
        remaining = self._construct_layered_routes(
            ordered_jobs,
            routes,
            engineers_by_id,
            jobs_by_id,
            layers_by_request,
            layer_ranks,
            planning_input,
        )
        self._complete_greedily(
            remaining,
            routes,
            engineers_by_id,
            jobs_by_id,
            layers_by_request,
            layer_ranks,
            planning_input,
        )
        return {
            engineer_id: request_ids for engineer_id, request_ids in routes.items() if request_ids
        }

    def assign_baseline(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        """Официальный baseline: входной порядок, первый подходящий инженер, только в конец."""

        jobs_by_id = {job.id: job for job in planning_input.jobs}
        layers_by_request = self.index_layers(planning_input.layers, jobs_by_id)
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {
            engineer.id: () for engineer in planning_input.engineers
        }
        for job in planning_input.jobs:
            for engineer in planning_input.engineers:
                if not self.eligible(engineer, job):
                    continue
                proposed_ids = (*routes[engineer.id], job.id)
                if (
                    self._materializer.materialize(
                        engineer,
                        proposed_ids,
                        jobs_by_id,
                        layers_by_request,
                        planning_input.calculation_cutoff_at,
                    )
                    is None
                ):
                    continue
                routes[engineer.id] = proposed_ids
                break
        return {
            engineer_id: request_ids for engineer_id, request_ids in routes.items() if request_ids
        }

    def assign_priority_append_seed(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        """Строит дешёвый seed с учётом приоритета и вставкой только в конец маршрута."""

        jobs_by_id = {job.id: job for job in planning_input.jobs}
        engineers_by_id = {engineer.id: engineer for engineer in planning_input.engineers}
        layers_by_request = self.index_layers(planning_input.layers, jobs_by_id)
        layer_ranks = self._layer_ranks(planning_input.layers)
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {
            engineer.id: () for engineer in planning_input.engineers
        }
        for job in self._ordered_jobs(planning_input.jobs):
            candidate = self._best_insertion(
                job,
                routes,
                engineers_by_id,
                jobs_by_id,
                layers_by_request,
                layer_ranks,
                planning_input,
                append_only=True,
            )
            if candidate is not None:
                routes[candidate.engineer_id] = candidate.request_ids
        return {
            engineer_id: request_ids for engineer_id, request_ids in routes.items() if request_ids
        }

    def complete(
        self,
        jobs: Sequence[Job],
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
        planning_input: InitialPlanningInput,
    ) -> None:
        """Жадно вставляет переданные остатки в уже построенные маршруты."""

        jobs_by_id = {job.id: job for job in planning_input.jobs}
        engineers_by_id = {engineer.id: engineer for engineer in planning_input.engineers}
        layers_by_request = self.index_layers(planning_input.layers, jobs_by_id)
        self._complete_greedily(
            self._ordered_jobs(jobs),
            routes,
            engineers_by_id,
            jobs_by_id,
            layers_by_request,
            self._layer_ranks(planning_input.layers),
            planning_input,
        )

    def eligible(self, engineer: Engineer, job: Job) -> bool:
        if not engineer.is_available:
            return False
        if job.required_skill not in engineer.skills:
            return False
        return (
            job.required_vehicle_type is None or job.required_vehicle_type == engineer.vehicle_type
        )

    def index_layers(
        self,
        layers: Sequence[PlanningLayer],
        jobs_by_id: dict[uuid.UUID, Job],
    ) -> dict[uuid.UUID, PlanningLayer]:
        indexed: dict[uuid.UUID, PlanningLayer] = {}
        for layer in layers:
            midpoint = layer.window_start + (layer.window_end - layer.window_start) / 2
            if layer.traffic_reference_at != midpoint:
                raise AlgorithmInputError("traffic_reference_at должен быть серединой окна")
            vehicle_types = [item.vehicle_type for item in layer.matrices]
            if len(vehicle_types) != len(set(vehicle_types)):
                raise AlgorithmInputError("В слое повторяется матрица одного типа транспорта")
            for request_id in layer.request_ids:
                if request_id not in jobs_by_id or request_id in indexed:
                    raise AlgorithmInputError("Слои содержат неизвестную или повторную заявку")
                indexed[request_id] = layer
        if set(indexed) != set(jobs_by_id):
            raise AlgorithmInputError("Каждая заявка должна принадлежать ровно одному слою")
        return indexed

    def _construct_layered_routes(
        self,
        jobs: Sequence[Job],
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
        engineers_by_id: dict[uuid.UUID, Engineer],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        layer_ranks: dict[uuid.UUID, int],
        planning_input: InitialPlanningInput,
    ) -> list[Job]:
        remaining: list[Job] = []
        for job in jobs:
            candidate = self._best_insertion(
                job,
                routes,
                engineers_by_id,
                jobs_by_id,
                layers_by_request,
                layer_ranks,
                planning_input,
                append_only=False,
            )
            if candidate is None:
                remaining.append(job)
                continue
            routes[candidate.engineer_id] = candidate.request_ids
        return remaining

    def _complete_greedily(
        self,
        jobs: Sequence[Job],
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
        engineers_by_id: dict[uuid.UUID, Engineer],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        layer_ranks: dict[uuid.UUID, int],
        planning_input: InitialPlanningInput,
    ) -> None:
        pending = list(jobs)
        changed = True
        while changed:
            changed = False
            for job in tuple(pending):
                candidate = self._best_insertion(
                    job,
                    routes,
                    engineers_by_id,
                    jobs_by_id,
                    layers_by_request,
                    layer_ranks,
                    planning_input,
                    append_only=False,
                )
                if candidate is None:
                    continue
                routes[candidate.engineer_id] = candidate.request_ids
                pending.remove(job)
                changed = True

    def _best_insertion(
        self,
        job: Job,
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
        engineers_by_id: dict[uuid.UUID, Engineer],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        layer_ranks: dict[uuid.UUID, int],
        planning_input: InitialPlanningInput,
        *,
        append_only: bool,
    ) -> _InsertionCandidate | None:
        candidates: list[_InsertionCandidate] = []
        for engineer in engineers_by_id.values():
            if not self.eligible(engineer, job):
                continue
            current_ids = routes[engineer.id]
            current_stops = self._materializer.materialize(
                engineer,
                current_ids,
                jobs_by_id,
                layers_by_request,
                planning_input.calculation_cutoff_at,
            )
            positions = (len(current_ids),) if append_only else range(len(current_ids) + 1)
            for position in positions:
                proposed_ids = (*current_ids[:position], job.id, *current_ids[position:])
                proposed_ranks = [layer_ranks[request_id] for request_id in proposed_ids]
                if proposed_ranks != sorted(proposed_ranks):
                    continue
                proposed_stops = self._materializer.materialize(
                    engineer,
                    proposed_ids,
                    jobs_by_id,
                    layers_by_request,
                    planning_input.calculation_cutoff_at,
                )
                if proposed_stops is None:
                    continue
                current_travel = sum(stop.travel_minutes for stop in current_stops or ())
                projected_travel = sum(stop.travel_minutes for stop in proposed_stops)
                candidates.append(
                    _InsertionCandidate(
                        engineer_id=engineer.id,
                        position=position,
                        request_ids=proposed_ids,
                        stops=proposed_stops,
                        added_travel_minutes=projected_travel - current_travel,
                        projected_service_minutes=sum(
                            jobs_by_id[request_id].service_minutes for request_id in proposed_ids
                        ),
                    )
                )
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda candidate: self._candidate_key(candidate, routes, planning_input.mode),
        )

    @staticmethod
    def _ordered_jobs(jobs: Sequence[Job]) -> list[Job]:
        return sorted(
            jobs,
            key=lambda job: (
                not job.is_emergency,
                job.latest_start_at,
                job.priority,
                str(job.id),
            ),
        )

    def _layer_ranks(self, layers: Sequence[PlanningLayer]) -> dict[uuid.UUID, int]:
        ordered_layers = sorted(layers, key=lambda layer: (layer.window_start, layer.window_end))
        return {
            request_id: rank
            for rank, layer in enumerate(ordered_layers)
            for request_id in layer.request_ids
        }

    def _candidate_key(
        self,
        candidate: _InsertionCandidate,
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
        mode: DistributionMode,
    ) -> tuple[int, int, int, str, int]:
        mode_score = (
            int(not routes[candidate.engineer_id])
            if mode == DistributionMode.MIN_ENGINEERS
            else candidate.projected_service_minutes
        )
        return (
            mode_score,
            candidate.added_travel_minutes,
            candidate.projected_service_minutes,
            str(candidate.engineer_id),
            candidate.position,
        )
