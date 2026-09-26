import uuid

from src.core.algorithm.dto import InitialPlanningInput
from src.core.algorithm.materialization import ScheduleMaterializer
from src.core.algorithm.rules import PlanningRules


class BaselinePlanner:
    """Официальный baseline п. 2.3 ТЗ; используется только для сравнения метрик.

    Заявки обходятся во входном порядке, каждая достаётся первому во входном порядке
    подходящему инженеру и дописывается только в конец его маршрута. Сортировки по
    приоритету, поиска лучшего инженера и перестановок нет.
    """

    def __init__(self) -> None:
        self._materializer = ScheduleMaterializer()

    def assign(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        layers_by_request = PlanningRules.index_layers(planning_input.layers, jobs_by_id)
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {
            engineer.id: () for engineer in planning_input.engineers
        }
        for job in planning_input.jobs:
            for engineer in planning_input.engineers:
                if not PlanningRules.eligible(engineer, job):
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
