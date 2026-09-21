import uuid
from collections import defaultdict
from collections.abc import Sequence

from src.core.algorithm.contracts import PlanningAlgorithm
from src.core.algorithm.dto import (
    DistributionResult,
    EngineerContext,
    EngineerPlanningContext,
    Job,
    Route,
    TravelMatrix,
    UnassignedJob,
)
from src.core.algorithm.enums import DistributionMode
from src.core.db.enums import UnassignedReason


class DistributionPlanner:
    """Распределяет заявки округа между инженерами округа одной стратегией.

    См. `docs/ALGORITHM.md`, "Пул допустимых заявок" — строит пул по
    skill/vehicle для каждого инженера (пулы могут пересекаться), сортирует
    инженеров по режиму и жадно прогоняет каждого через выбранную стратегию
    планирования, вычитая занятые в его маршруте заявки из пулов оставшихся
    необработанных инженеров.

    Фильтрация по округу — забота вызывающего кода (`AlgorithmService`):
    `engineers`/`jobs` здесь всегда относятся к одному округу, потому что
    округа планируются независимо (см. `DATABASE.md`).
    """

    def __init__(self, strategy: PlanningAlgorithm) -> None:
        self._strategy = strategy

    def assign(
        self,
        engineers: Sequence[EngineerContext],
        jobs: Sequence[Job],
        travel_matrix: TravelMatrix,
        mode: DistributionMode,
        budget_seconds: float | None = None,
    ) -> DistributionResult:
        """Строит маршруты всех инженеров округа и список неразмещённых заявок.

        Args:
            engineers: инженеры одного округа.
            jobs: заявки того же округа.
            travel_matrix: матрица времени/расстояния, покрывающая все
                переданные точки (старты инженеров + адреса заявок).
            mode: `MIN_ENGINEERS` — сначала самые загруженные пулом
                инженеры, `BALANCED` — сначала наименее загруженные.
            budget_seconds: сколько секунд стратегия тратит на маршрут
                одного инженера; по умолчанию — `strategy.DEFAULT_BUDGET_SECONDS`.

        Returns:
            Маршруты по каждому задействованному инженеру и причины отказа
            по каждой неразмещённой заявке.
        """
        pools = self._build_pools(engineers, jobs)
        ordered_engineers = self._order_engineers(engineers, pools, mode)
        effective_budget = budget_seconds or self._strategy.DEFAULT_BUDGET_SECONDS

        remaining_job_ids = {job.id for job in jobs}
        routes: list[Route] = []
        for engineer in ordered_engineers:
            pool = tuple(job for job in pools.get(engineer.id, ()) if job.id in remaining_job_ids)
            if not pool:
                continue
            context = EngineerPlanningContext(
                engineer=engineer, jobs=pool, travel_matrix=travel_matrix
            )
            route = self._strategy.plan_initial(context, effective_budget)
            if route.stops:
                routes.append(route)
                remaining_job_ids -= route.assigned_job_ids

        jobs_by_id = {job.id: job for job in jobs}
        unassigned = tuple(
            UnassignedJob(
                job_id=job_id,
                reason=self._resolve_unassigned_reason(jobs_by_id[job_id], engineers),
            )
            for job_id in remaining_job_ids
        )
        return DistributionResult(routes=tuple(routes), unassigned=unassigned)

    def _build_pools(
        self, engineers: Sequence[EngineerContext], jobs: Sequence[Job]
    ) -> dict[uuid.UUID, tuple[Job, ...]]:
        pools: dict[uuid.UUID, list[Job]] = defaultdict(list)
        for engineer in engineers:
            for job in jobs:
                if job.required_skill not in engineer.skills:
                    continue
                if (
                    job.required_vehicle_type is not None
                    and job.required_vehicle_type != engineer.vehicle_type
                ):
                    continue
                pools[engineer.id].append(job)
        return {engineer_id: tuple(pool) for engineer_id, pool in pools.items()}

    def _order_engineers(
        self,
        engineers: Sequence[EngineerContext],
        pools: dict[uuid.UUID, tuple[Job, ...]],
        mode: DistributionMode,
    ) -> list[EngineerContext]:
        reverse = mode == DistributionMode.MIN_ENGINEERS
        return sorted(
            engineers, key=lambda engineer: len(pools.get(engineer.id, ())), reverse=reverse
        )

    def _resolve_unassigned_reason(
        self, job: Job, engineers: Sequence[EngineerContext]
    ) -> UnassignedReason:
        skill_matches = [
            engineer for engineer in engineers if job.required_skill in engineer.skills
        ]
        if not skill_matches:
            return UnassignedReason.NO_MATCHING_SKILL

        vehicle_matches = [
            engineer
            for engineer in skill_matches
            if job.required_vehicle_type is None
            or job.required_vehicle_type == engineer.vehicle_type
        ]
        if not vehicle_matches:
            return UnassignedReason.NO_MATCHING_VEHICLE

        fits_any_shift = any(
            job.window_start < engineer.shift_end and job.window_end > engineer.shift_start
            for engineer in vehicle_matches
        )
        if not fits_any_shift:
            return UnassignedReason.NO_TIME_SLOT

        return UnassignedReason.NO_AVAILABLE_ENGINEER
