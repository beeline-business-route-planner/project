import uuid
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from src.core.algorithm.audit import ResultAuditor
from src.core.algorithm.diagnostics import AlgorithmDiagnostics
from src.core.algorithm.dto import (
    BasePlanStop,
    DiagnosedPlanningResult,
    Engineer,
    InitialPlanningDraft,
    InitialPlanningInput,
    InitialPlanningResult,
    InitialPlanningSnapshot,
    Job,
    LayerMatrix,
    ManualDiagnosis,
    ManualIssue,
    PlanMetrics,
    PlanningLayer,
    ReplanDraft,
    ReplanEvent,
    ReplanInput,
    ReplanResult,
    ReplanSnapshot,
    Route,
    Stop,
    UnassignedJob,
)
from src.core.algorithm.enums import AlgorithmVariant, ManualIssueCode
from src.core.algorithm.exc import AlgorithmAuditError, ManualRouteViolationError
from src.core.algorithm.materialization import ScheduleMaterializer
from src.core.algorithm.normalization import InitialInputNormalizer, ReplanNormalizer
from src.core.algorithm.rules import PlanningRules
from src.core.algorithm.strategies.baseline import BaselinePlanner
from src.core.algorithm.strategies.graph import LayeredGraphPlanner
from src.core.algorithm.strategies.greedy import GreedyPlanner
from src.core.algorithm.strategies.lns import LnsPlanner
from src.core.db.enums import UnassignedReason


class AlgorithmService:
    """Чистый планировщик initial: без БД, HTTP, часов, routing и commit."""

    def __init__(self) -> None:
        self._normalizer = InitialInputNormalizer()
        self._materializer = ScheduleMaterializer()
        self._auditor = ResultAuditor()
        self._replan_normalizer = ReplanNormalizer()

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

    def plan_manual_initial(
        self,
        planning_input: InitialPlanningInput,
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
    ) -> InitialPlanningResult:
        self._validate_manual_routes(planning_input, routes)
        result = self._result(planning_input, routes, "manual-v1")
        self._auditor.audit(planning_input, result)
        return result

    def plan_manual_replan(
        self,
        replan_input: ReplanInput,
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
    ) -> ReplanResult:
        self._validate_manual_routes(replan_input.tail, routes)
        tail = self._result(replan_input.tail, routes, "manual-v1")
        self._auditor.audit(replan_input.tail, tail)
        result = self._merge_replan(replan_input, tail)
        self._auditor.audit_replan(replan_input, result)
        return result

    def _validate_manual_routes(
        self,
        planning_input: InitialPlanningInput,
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
    ) -> None:
        engineers = {engineer.id: engineer for engineer in planning_input.engineers}
        jobs = {job.id: job for job in planning_input.jobs}
        layers = PlanningRules.index_layers(planning_input.layers, jobs)
        assigned: set[uuid.UUID] = set()
        issues: list[ManualIssue] = []
        diagnosed_stops: dict[uuid.UUID, tuple[Stop, ...]] = {}
        for engineer_id, request_ids in routes.items():
            engineer = engineers.get(engineer_id)
            known_ids: list[uuid.UUID] = []
            for request_id in request_ids:
                job = jobs.get(request_id)
                if job is None:
                    issues.append(
                        ManualIssue(request_id, engineer_id, ManualIssueCode.UNKNOWN_REQUEST)
                    )
                    continue
                if request_id in assigned:
                    issues.append(
                        ManualIssue(request_id, engineer_id, ManualIssueCode.DUPLICATE_REQUEST)
                    )
                    continue
                assigned.add(request_id)
                if engineer is None:
                    issues.append(
                        ManualIssue(request_id, engineer_id, ManualIssueCode.UNKNOWN_ENGINEER)
                    )
                    continue
                if not engineer.is_available:
                    issues.append(
                        ManualIssue(request_id, engineer_id, ManualIssueCode.ENGINEER_UNAVAILABLE)
                    )
                if job.required_skill not in engineer.skills:
                    issues.append(ManualIssue(request_id, engineer_id, ManualIssueCode.SKILL))
                if (
                    job.required_vehicle_type is not None
                    and job.required_vehicle_type != engineer.vehicle_type
                ):
                    issues.append(ManualIssue(request_id, engineer_id, ManualIssueCode.VEHICLE))
                known_ids.append(request_id)
            if engineer is not None and known_ids:
                stops, timing_issues = self._materializer.diagnose(
                    engineer, known_ids, jobs, layers, planning_input.calculation_cutoff_at
                )
                diagnosed_stops[engineer_id] = stops
                issues.extend(timing_issues)
        if issues:
            raise ManualRouteViolationError(ManualDiagnosis(diagnosed_stops, tuple(issues)))

    def plan_initial_diagnosed(
        self,
        planning_input: InitialPlanningInput,
        variant: AlgorithmVariant = AlgorithmVariant.LAYERED_GRAPH,
    ) -> DiagnosedPlanningResult:
        """Запускает тот же расчёт с несохраняемой диагностикой времени."""

        diagnostics = AlgorithmDiagnostics()
        result = self._plan(planning_input, variant, diagnostics)
        return DiagnosedPlanningResult(result=result, diagnostics=diagnostics.report())

    def prepare_replan(self, snapshot: ReplanSnapshot) -> ReplanDraft:
        """Фиксирует прожитую историю утверждённого плана и описывает матрицы хвоста.

        Args:
            snapshot: утверждённый план округа, актуальные заявки/инженеры и cutoff.

        Returns:
            Зафиксированные остановки, отменённые заявки и черновик хвоста с запросами
            матриц; стартовая точка инженера в черновике — конец его истории.

        Raises:
            AlgorithmInputError: если базовый план не согласован со snapshot.
            MissingCoordinatesError: если у заявки или стартовой точки нет координат.
        """

        return self._replan_normalizer.prepare(snapshot)

    def prepare_event_replan(self, snapshot: ReplanSnapshot, event: ReplanEvent) -> ReplanDraft:
        """Применяет одно внештатное событие к утверждённому плану и готовит его replan.

        Дальше расчёт идёт обычными `build_replan_input` и `plan_replan`; аудит результата
        дополнительно проверяет, что событие применено ровно один раз.

        Raises:
            AlgorithmInputError: если событие не согласовано со snapshot.
            MissingCoordinatesError: если у заявки или стартовой точки нет координат.
        """

        return self._replan_normalizer.prepare_event(snapshot, event)

    def build_replan_input(
        self,
        draft: ReplanDraft,
        matrices: Sequence[LayerMatrix],
    ) -> ReplanInput:
        return self._replan_normalizer.build(draft, matrices)

    def plan_replan(
        self,
        replan_input: ReplanInput,
        variant: AlgorithmVariant = AlgorithmVariant.LAYERED_GRAPH,
    ) -> ReplanResult:
        """Пересчитывает будущий хвост и возвращает полный план дня с неизменной историей.

        Хвост считается выбранной стратегией и проходит обычный аудит initial, затем
        склеивается с locked history и проверяется аудитом replan.

        Raises:
            AlgorithmAuditError: если результат нарушает инвариант истории или покрытия.
        """

        tail = self._not_worse_than_current(
            replan_input.tail, self._plan(replan_input.tail, variant, None)
        )
        result = self._merge_replan(replan_input, tail)
        self._auditor.audit_replan(replan_input, result)
        return result

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
        result = self._result(planning_input, ordered_routes, f"{variant.value}-v3")
        if diagnostics is not None:
            diagnostics.finish_result_build()
        self._auditor.audit(planning_input, result)
        if diagnostics is not None:
            diagnostics.finish_audit()
        return result

    def _not_worse_than_current(
        self,
        planning_input: InitialPlanningInput,
        tail: InitialPlanningResult,
    ) -> InitialPlanningResult:
        """Возвращает известное решение хвоста, если оно покрывает больше найденного.

        Сравнение идёт только по приоритету и покрытию: цель режима и дорогу оптимизирует
        стратегия, а известное решение лишь страхует от потери заявок.
        """

        best = tail
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        layers_by_request = PlanningRules.index_layers(planning_input.layers, jobs_by_id)
        for solution in planning_input.known_solutions:
            routes = self._materializer.feasible_routes(planning_input, solution, layers_by_request)
            if routes is None:
                continue
            candidate = self._result(planning_input, routes, tail.algorithm_version)
            if self._coverage_key(candidate, jobs_by_id) > self._coverage_key(best, jobs_by_id):
                self._auditor.audit(planning_input, candidate)
                best = candidate
        return best

    @staticmethod
    def _coverage_key(
        result: InitialPlanningResult,
        jobs_by_id: dict[uuid.UUID, Job],
    ) -> tuple[int, int]:
        request_ids = [stop.request_id for route in result.routes for stop in route.stops]
        return (
            sum(PlanningRules.priority_score(jobs_by_id[item].priority) for item in request_ids),
            len(request_ids),
        )

    def _result(
        self,
        planning_input: InitialPlanningInput,
        ordered_routes: dict[uuid.UUID, tuple[uuid.UUID, ...]],
        algorithm_version: str,
    ) -> InitialPlanningResult:
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
        return InitialPlanningResult(
            region=planning_input.region,
            planning_date=planning_input.planning_date,
            calculation_cutoff_at=planning_input.calculation_cutoff_at,
            mode=planning_input.mode,
            routes=routes,
            unassigned=unassigned,
            metrics=self._metrics(routes, unassigned, planning_input.engineers),
            algorithm_version=algorithm_version,
        )

    def _merge_replan(
        self,
        replan_input: ReplanInput,
        tail: InitialPlanningResult,
    ) -> ReplanResult:
        service_minutes = {
            request.id: request.service_minutes for request in replan_input.snapshot.requests
        }
        engineers_by_id = {engineer.id: engineer for engineer in replan_input.tail.engineers}
        locked_by_engineer: dict[uuid.UUID, list[BasePlanStop]] = {}
        for locked_stop in replan_input.locked_stops:
            locked_by_engineer.setdefault(locked_stop.engineer_id, []).append(locked_stop)
        tail_by_engineer = {route.engineer_id: route.stops for route in tail.routes}
        routes = []
        for engineer_id in sorted(
            set(locked_by_engineer) | set(tail_by_engineer), key=lambda item: str(item)
        ):
            locked = [
                Stop(
                    request_id=stop.request_id,
                    sequence_number=stop.sequence_number,
                    arrival=stop.arrival,
                    start=stop.start,
                    finish=stop.finish,
                    travel_minutes=stop.travel_minutes,
                    distance_km=stop.distance_km,
                    is_locked=True,
                )
                for stop in sorted(
                    locked_by_engineer.get(engineer_id, ()), key=lambda item: item.sequence_number
                )
            ]
            future = [
                replace(stop, sequence_number=len(locked) + index)
                for index, stop in enumerate(tail_by_engineer.get(engineer_id, ()), start=1)
            ]
            routes.append(
                self._full_day_route(
                    engineers_by_id[engineer_id], (*locked, *future), service_minutes
                )
            )
        full_routes = tuple(routes)
        return ReplanResult(
            region=tail.region,
            planning_date=tail.planning_date,
            calculation_cutoff_at=tail.calculation_cutoff_at,
            mode=tail.mode,
            routes=full_routes,
            unassigned=tail.unassigned,
            cancelled_request_ids=tuple(
                sorted(replan_input.cancelled_request_ids, key=lambda item: str(item))
            ),
            metrics=self._metrics(full_routes, tail.unassigned, replan_input.tail.engineers),
            algorithm_version=f"replan-{tail.algorithm_version}",
        )

    @staticmethod
    def _full_day_route(
        engineer: Engineer,
        stops: tuple[Stop, ...],
        service_minutes: dict[uuid.UUID, int],
    ) -> Route:
        service = sum(service_minutes[stop.request_id] for stop in stops)
        travel = sum(stop.travel_minutes for stop in stops)
        shift_minutes = int((engineer.shift_end - engineer.shift_start).total_seconds() // 60)
        if shift_minutes <= 0:
            raise AlgorithmAuditError("Смена инженера должна иметь положительную длину")
        return Route(
            engineer_id=engineer.id,
            stops=stops,
            service_minutes=service,
            travel_minutes=travel,
            distance_km=sum((stop.distance_km for stop in stops), start=Decimal("0")),
            utilization_without_travel=Decimal(service) / Decimal(shift_minutes),
            utilization_with_travel=Decimal(service + travel) / Decimal(shift_minutes),
        )

    def _assign(
        self,
        planning_input: InitialPlanningInput,
        variant: AlgorithmVariant,
        diagnostics: AlgorithmDiagnostics | None,
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        match variant:
            case AlgorithmVariant.LAYERED_GRAPH:
                return LayeredGraphPlanner(diagnostics).assign(planning_input)
            case AlgorithmVariant.LNS:
                return LnsPlanner(diagnostics).assign(planning_input)
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
        if not any(engineer.is_available for engineer in engineers):
            return UnassignedReason.NO_AVAILABLE_ENGINEER
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
            self._reachable(engineer, job, planning_input, layers_by_request)
            for engineer in available_matches
        ):
            return UnassignedReason.NO_ROUTE
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

    @staticmethod
    def _reachable(
        engineer: Engineer,
        job: Job,
        planning_input: InitialPlanningInput,
        layers_by_request: dict[uuid.UUID, PlanningLayer],
    ) -> bool:
        """Есть ли у инженера хоть один переход в заявку: со старта или с заявки не позже слоя."""

        layer = layers_by_request[job.id]
        matrix = next(
            item.travel_matrix
            for item in layer.matrices
            if item.vehicle_type == engineer.vehicle_type
        )
        sources = [engineer.id] + [
            other.id
            for other in planning_input.jobs
            if other.id != job.id and layers_by_request[other.id].window_start <= layer.window_start
        ]
        for source_id in sources:
            try:
                if matrix.minutes(source_id, job.id) is not None:
                    return True
            except KeyError:
                continue
        return False

    def _metrics(
        self,
        routes: tuple[Route, ...],
        unassigned: tuple[UnassignedJob, ...],
        engineers: tuple[Engineer, ...],
    ) -> PlanMetrics:
        available_count = sum(engineer.is_available for engineer in engineers)
        routed_ids = {route.engineer_id for route in routes}
        counted = sum(engineer.is_available or engineer.id in routed_ids for engineer in engineers)
        utilization_without = sum(
            (route.utilization_without_travel for route in routes), start=Decimal("0")
        )
        utilization_with = sum(
            (route.utilization_with_travel for route in routes), start=Decimal("0")
        )
        # Среднее по всем, кто мог работать или работал: выбывший после утренней истории
        # остаётся в знаменателе, иначе его загрузка завышала бы среднее.
        divisor = Decimal(counted) if counted else Decimal("1")
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
