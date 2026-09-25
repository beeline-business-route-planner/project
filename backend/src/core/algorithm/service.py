import uuid
from collections.abc import Sequence
from decimal import Decimal

from src.core.algorithm.audit import ResultAuditor
from src.core.algorithm.diagnostics import AlgorithmDiagnostics
from src.core.algorithm.dto import (
    DiagnosedPlanningResult,
    Engineer,
    InitialPlanningDraft,
    InitialPlanningInput,
    InitialPlanningResult,
    InitialPlanningSnapshot,
    Job,
    LayerMatrix,
    PlanMetrics,
    PlanningLayer,
    Route,
    Stop,
    UnassignedJob,
)
from src.core.algorithm.enums import AlgorithmVariant
from src.core.algorithm.exc import AlgorithmAuditError
from src.core.algorithm.materialization import ScheduleMaterializer
from src.core.algorithm.normalization import InitialInputNormalizer
from src.core.algorithm.rules import PlanningRules
from src.core.algorithm.strategies.baseline import BaselinePlanner
from src.core.algorithm.strategies.graph import LayeredGraphPlanner
from src.core.algorithm.strategies.greedy import GreedyPlanner
from src.core.db.enums import UnassignedReason


class AlgorithmService:
    """Чистый планировщик initial: без БД, HTTP, часов, routing и commit."""

    def __init__(self) -> None:
        self._normalizer = InitialInputNormalizer()
        self._materializer = ScheduleMaterializer()
        self._auditor = ResultAuditor()

    def prepare_initial(self, snapshot: InitialPlanningSnapshot) -> InitialPlanningDraft:
        """Нормализует данные округа и перечисляет матрицы, которые нужно получить.

        Args:
            snapshot: сырые заявки и инженеры округа и единый cutoff расчёта.

        Returns:
            Черновик с эффективными окнами и запросами матриц по слоям и транспорту.

        Raises:
            MissingCoordinatesError: если у заявки или старта инженера нет координат.
        """

        return self._normalizer.prepare(snapshot)

    def build_initial_input(
        self,
        draft: InitialPlanningDraft,
        matrices: Sequence[LayerMatrix],
    ) -> InitialPlanningInput:
        return self._normalizer.build(draft, matrices)

    def plan_initial(
        self,
        planning_input: InitialPlanningInput,
        variant: AlgorithmVariant = AlgorithmVariant.LAYERED_GRAPH,
    ) -> InitialPlanningResult:
        return self._plan(planning_input, variant, None)

    def plan_baseline(self, planning_input: InitialPlanningInput) -> InitialPlanningResult:
        """Считает официальный baseline п. 2.3 ТЗ на том же входе и с тем же аудитом."""

        return self._plan(planning_input, AlgorithmVariant.BASELINE, None)

    def plan_initial_diagnosed(
        self,
        planning_input: InitialPlanningInput,
        variant: AlgorithmVariant = AlgorithmVariant.LAYERED_GRAPH,
    ) -> DiagnosedPlanningResult:
        """Запускает тот же расчёт с несохраняемой диагностикой времени."""

        diagnostics = AlgorithmDiagnostics()
        result = self._plan(planning_input, variant, diagnostics)
        return DiagnosedPlanningResult(result=result, diagnostics=diagnostics.report())

    def _plan(
        self,
        planning_input: InitialPlanningInput,
        variant: AlgorithmVariant,
        diagnostics: AlgorithmDiagnostics | None,
    ) -> InitialPlanningResult:
        if diagnostics is not None:
            diagnostics.start()
        ordered_routes = self._assign(planning_input, variant, diagnostics)
        if diagnostics is not None:
            diagnostics.finish_assignment()
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        engineers_by_id = {engineer.id: engineer for engineer in planning_input.engineers}
        layers_by_request = PlanningRules.index_layers(planning_input.layers, jobs_by_id)
        routes = tuple(
            self._build_route(
                engineers_by_id[engineer_id],
                self._materialize_final_route(
                    engineers_by_id[engineer_id],
                    request_ids,
                    jobs_by_id,
                    layers_by_request,
                    planning_input,
                ),
                jobs_by_id,
            )
            for engineer_id, request_ids in sorted(
                ordered_routes.items(), key=lambda item: str(item[0])
            )
        )
        assigned_ids = {stop.request_id for route in routes for stop in route.stops}
        unassigned = tuple(
            UnassignedJob(
                job.id,
                self._unassigned_reason(job, planning_input, layers_by_request),
            )
            for job in sorted(planning_input.jobs, key=lambda item: str(item.id))
            if job.id not in assigned_ids
        )
        result = InitialPlanningResult(
            region=planning_input.region,
            planning_date=planning_input.planning_date,
            calculation_cutoff_at=planning_input.calculation_cutoff_at,
            mode=planning_input.mode,
            routes=routes,
            unassigned=unassigned,
            metrics=self._metrics(routes, unassigned, planning_input.engineers),
            algorithm_version=f"{variant.value}-v2",
        )
        if diagnostics is not None:
            diagnostics.finish_result_build()
        self._auditor.audit(planning_input, result)
        if diagnostics is not None:
            diagnostics.finish_audit()
        return result

    def _assign(
        self,
        planning_input: InitialPlanningInput,
        variant: AlgorithmVariant,
        diagnostics: AlgorithmDiagnostics | None,
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        match variant:
            case AlgorithmVariant.LAYERED_GRAPH:
                return LayeredGraphPlanner(diagnostics).assign(planning_input)
            case AlgorithmVariant.GREEDY:
                return GreedyPlanner().assign(planning_input)
            case AlgorithmVariant.BASELINE:
                return BaselinePlanner().assign(planning_input)
        raise ValueError(f"Неизвестный вариант алгоритма: {variant}")

    def _materialize_final_route(
        self,
        engineer: Engineer,
        request_ids: tuple[uuid.UUID, ...],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        planning_input: InitialPlanningInput,
    ) -> tuple[Stop, ...]:
        stops = self._materializer.materialize(
            engineer,
            request_ids,
            jobs_by_id,
            layers_by_request,
            planning_input.calculation_cutoff_at,
        )
        if stops is None:
            raise AlgorithmAuditError("Выбранный порядок невозможно материализовать")
        return stops

    def _build_route(
        self,
        engineer: Engineer,
        stops: tuple[Stop, ...],
        jobs_by_id: dict[uuid.UUID, Job],
    ) -> Route:
        service_minutes = sum(jobs_by_id[stop.request_id].service_minutes for stop in stops)
        travel_minutes = sum(stop.travel_minutes for stop in stops)
        distance_km = sum((stop.distance_km for stop in stops), start=Decimal("0"))
        shift_minutes = int((engineer.shift_end - engineer.shift_start).total_seconds() // 60)
        if shift_minutes <= 0:
            raise AlgorithmAuditError("Смена инженера должна иметь положительную длину")
        without_travel = Decimal(service_minutes) / Decimal(shift_minutes)
        with_travel = Decimal(service_minutes + travel_minutes) / Decimal(shift_minutes)
        return Route(
            engineer_id=engineer.id,
            stops=stops,
            service_minutes=service_minutes,
            travel_minutes=travel_minutes,
            distance_km=distance_km,
            utilization_without_travel=without_travel,
            utilization_with_travel=with_travel,
        )

    def _unassigned_reason(
        self,
        job: Job,
        planning_input: InitialPlanningInput,
        layers_by_request: dict[uuid.UUID, PlanningLayer],
    ) -> UnassignedReason:
        engineers = planning_input.engineers
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
        available_matches = [engineer for engineer in vehicle_matches if engineer.is_available]
        if not available_matches:
            return UnassignedReason.NO_AVAILABLE_ENGINEER
        if not any(
            self._materializer.materialize(
                engineer,
                (job.id,),
                {job.id: job},
                layers_by_request,
                planning_input.calculation_cutoff_at,
            )
            is not None
            for engineer in available_matches
        ):
            return UnassignedReason.NO_TIME_SLOT
        return UnassignedReason.NO_AVAILABLE_ENGINEER

    def _metrics(
        self,
        routes: tuple[Route, ...],
        unassigned: tuple[UnassignedJob, ...],
        engineers: tuple[Engineer, ...],
    ) -> PlanMetrics:
        available_count = sum(engineer.is_available for engineer in engineers)
        utilization_without = sum(
            (route.utilization_without_travel for route in routes), start=Decimal("0")
        )
        utilization_with = sum(
            (route.utilization_with_travel for route in routes), start=Decimal("0")
        )
        divisor = Decimal(available_count) if available_count else Decimal("1")
        return PlanMetrics(
            engineers_available_count=available_count,
            engineers_used_count=len(routes),
            assigned_requests_count=sum(len(route.stops) for route in routes),
            unassigned_requests_count=len(unassigned),
            total_service_minutes=sum(route.service_minutes for route in routes),
            total_travel_minutes=sum(route.travel_minutes for route in routes),
            total_mileage_km=sum((route.distance_km for route in routes), start=Decimal("0")),
            average_utilization_without_travel=utilization_without / divisor,
            average_utilization_with_travel=utilization_with / divisor,
        )
