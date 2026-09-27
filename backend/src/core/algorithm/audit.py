import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from src.core.algorithm.dto import (
    BasePlanStop,
    Engineer,
    EngineerSnapshot,
    InitialPlanningInput,
    InitialPlanningResult,
    Job,
    PlanningLayer,
    ReplanInput,
    ReplanResult,
    Route,
    Stop,
)
from src.core.algorithm.exc import AlgorithmAuditError
from src.core.algorithm.rules import PlanningRules


class ResultAuditor:
    """Независимо проверяет жёсткие инварианты материализованного результата."""

    def audit(self, planning_input: InitialPlanningInput, result: InitialPlanningResult) -> None:
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        engineers_by_id = {engineer.id: engineer for engineer in planning_input.engineers}
        layers_by_request = {
            request_id: layer for layer in planning_input.layers for request_id in layer.request_ids
        }
        assigned_ids: list[uuid.UUID] = []
        for route in result.routes:
            engineer = engineers_by_id.get(route.engineer_id)
            if engineer is None:
                raise AlgorithmAuditError("Маршрут ссылается на неизвестного инженера")
            if not engineer.is_available:
                raise AlgorithmAuditError("Маршрут назначен недоступному инженеру")
            assigned_ids.extend(
                self._audit_route(
                    route,
                    engineer,
                    jobs_by_id,
                    layers_by_request,
                    planning_input.calculation_cutoff_at,
                )
            )
        self._audit_coverage(assigned_ids, jobs_by_id, result)
        self._audit_plan_metrics(planning_input, result, assigned_ids)

    def audit_replan(self, replan_input: ReplanInput, result: ReplanResult) -> None:
        """Проверяет полный план replan: неизменная история, хвост и покрытие дня.

        Хвост уже прошёл обычный аудит initial на входе хвоста; здесь проверяется то, что
        появилось при склейке: locked stops — точные копии базы и префикс маршрута, новые
        остановки не раньше cutoff и только у доступных инженеров, каждая заявка дня ровно
        один раз среди назначенных, неназначенных или отменённых, согласованные агрегаты.

        Raises:
            AlgorithmAuditError: при любом нарушении.
        """

        engineers_by_id = {engineer.id: engineer for engineer in replan_input.snapshot.engineers}
        expected_locked = {stop.request_id: stop for stop in replan_input.locked_stops}
        assigned_ids: list[uuid.UUID] = []
        seen_locked: set[uuid.UUID] = set()
        for route in result.routes:
            engineer = engineers_by_id.get(route.engineer_id)
            if engineer is None:
                raise AlgorithmAuditError("Маршрут ссылается на неизвестного инженера")
            assigned_ids.extend(
                self._audit_replan_route(
                    route,
                    engineer,
                    expected_locked,
                    seen_locked,
                    replan_input.snapshot.calculation_cutoff_at,
                )
            )
        if seen_locked != set(expected_locked):
            raise AlgorithmAuditError("Не все зафиксированные остановки перенесены в план")
        self._audit_replan_coverage(replan_input, result, assigned_ids)

    def _audit_replan_route(
        self,
        route: Route,
        engineer: EngineerSnapshot,
        expected_locked: dict[uuid.UUID, BasePlanStop],
        seen_locked: set[uuid.UUID],
        cutoff_at: datetime,
    ) -> list[uuid.UUID]:
        future_started = False
        for expected_sequence, stop in enumerate(route.stops, start=1):
            if stop.sequence_number != expected_sequence:
                raise AlgorithmAuditError("Нарушена непрерывность sequence_number")
            if stop.is_locked:
                base = expected_locked.get(stop.request_id)
                if future_started or base is None:
                    raise AlgorithmAuditError("Зафиксированная остановка вне прожитой истории")
                if not self._same_as_base(route.engineer_id, stop, base):
                    raise AlgorithmAuditError("Зафиксированная остановка изменена")
                seen_locked.add(stop.request_id)
                continue
            future_started = True
            if not engineer.is_available:
                raise AlgorithmAuditError("Недоступный инженер получил будущую остановку")
            if stop.start < cutoff_at:
                raise AlgorithmAuditError("Будущая остановка начинается раньше cutoff")
        return [stop.request_id for stop in route.stops]

    @staticmethod
    def _audit_replan_coverage(
        replan_input: ReplanInput,
        result: ReplanResult,
        assigned_ids: list[uuid.UUID],
    ) -> None:
        unassigned_ids = [item.job_id for item in result.unassigned]
        all_ids = [*assigned_ids, *unassigned_ids, *result.cancelled_request_ids]
        if len(all_ids) != len(set(all_ids)):
            raise AlgorithmAuditError("Заявка встретилась в плане больше одного раза")
        if set(all_ids) != {request.id for request in replan_input.snapshot.requests}:
            raise AlgorithmAuditError("План не покрывает полный набор заявок дня")
        if (
            result.metrics.assigned_requests_count,
            result.metrics.unassigned_requests_count,
            result.metrics.engineers_used_count,
            result.metrics.total_travel_minutes,
        ) != (
            len(assigned_ids),
            len(unassigned_ids),
            len(result.routes),
            sum(route.travel_minutes for route in result.routes),
        ):
            raise AlgorithmAuditError("Агрегаты replan не совпадают с маршрутами")

    @staticmethod
    def _same_as_base(engineer_id: uuid.UUID, stop: Stop, base: BasePlanStop) -> bool:
        return (
            engineer_id,
            stop.sequence_number,
            stop.arrival,
            stop.start,
            stop.finish,
            stop.travel_minutes,
            stop.distance_km,
        ) == (
            base.engineer_id,
            base.sequence_number,
            base.arrival,
            base.start,
            base.finish,
            base.travel_minutes,
            base.distance_km,
        )

    def _audit_route(
        self,
        route: Route,
        engineer: Engineer,
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_at: datetime,
    ) -> list[uuid.UUID]:
        previous_id = engineer.id
        previous_finish = max(engineer.available_from, cutoff_at)
        assigned_ids: list[uuid.UUID] = []
        service_minutes = 0
        travel_minutes = 0
        distance_km = Decimal("0")
        for expected_sequence, stop in enumerate(route.stops, start=1):
            job = self._audit_stop(
                stop,
                expected_sequence,
                engineer,
                previous_id,
                previous_finish,
                jobs_by_id,
                layers_by_request,
                cutoff_at,
            )
            assigned_ids.append(job.id)
            service_minutes += job.service_minutes
            travel_minutes += stop.travel_minutes
            distance_km += stop.distance_km
            previous_id = job.id
            previous_finish = stop.finish
        self._audit_route_metrics(
            route,
            engineer,
            service_minutes,
            travel_minutes,
            distance_km,
        )
        return assigned_ids

    def _audit_stop(
        self,
        stop: Stop,
        expected_sequence: int,
        engineer: Engineer,
        previous_id: uuid.UUID,
        previous_finish: datetime,
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_at: datetime,
    ) -> Job:
        job = jobs_by_id.get(stop.request_id)
        if job is None:
            raise AlgorithmAuditError("Маршрут ссылается на неизвестную заявку")
        if stop.sequence_number != expected_sequence:
            raise AlgorithmAuditError("Нарушена непрерывность sequence_number")
        if not PlanningRules.eligible(engineer, job):
            raise AlgorithmAuditError("Нарушено ограничение навыка или транспорта")
        layer = layers_by_request[job.id]
        matching_matrices = [
            item.travel_matrix
            for item in layer.matrices
            if item.vehicle_type == engineer.vehicle_type
        ]
        if len(matching_matrices) != 1:
            raise AlgorithmAuditError("Для маршрута отсутствует транспортная матрица")
        expected_travel = matching_matrices[0].minutes(previous_id, job.id)
        expected_distance = matching_matrices[0].kilometers(previous_id, job.id)
        if expected_travel is None or expected_distance is None:
            raise AlgorithmAuditError("Маршрут проходит через недостижимый переход")
        expected_arrival = previous_finish + timedelta(minutes=expected_travel)
        expected_start = max(expected_arrival, job.release_at, cutoff_at)
        expected_finish = expected_start + timedelta(minutes=job.service_minutes)
        expected_values = (
            expected_travel,
            expected_distance,
            expected_arrival,
            expected_start,
            expected_finish,
        )
        actual_values = (
            stop.travel_minutes,
            stop.distance_km,
            stop.arrival,
            stop.start,
            stop.finish,
        )
        if actual_values != expected_values:
            raise AlgorithmAuditError("Времена остановки не согласованы с маршрутом")
        if stop.start > job.latest_start_at or stop.finish > engineer.shift_end:
            raise AlgorithmAuditError("Нарушено окно заявки или граница смены")
        return job

    @staticmethod
    def _audit_route_metrics(
        route: Route,
        engineer: Engineer,
        service_minutes: int,
        travel_minutes: int,
        distance_km: Decimal,
    ) -> None:
        shift_minutes = int((engineer.shift_end - engineer.shift_start).total_seconds() // 60)
        if shift_minutes <= 0:
            raise AlgorithmAuditError("Смена инженера должна иметь положительную длину")
        expected_values = (
            service_minutes,
            travel_minutes,
            distance_km,
            Decimal(service_minutes) / Decimal(shift_minutes),
            Decimal(service_minutes + travel_minutes) / Decimal(shift_minutes),
        )
        actual_values = (
            route.service_minutes,
            route.travel_minutes,
            route.distance_km,
            route.utilization_without_travel,
            route.utilization_with_travel,
        )
        if actual_values != expected_values:
            raise AlgorithmAuditError("Агрегаты маршрута не совпадают с остановками")

    @staticmethod
    def _audit_coverage(
        assigned_ids: list[uuid.UUID],
        jobs_by_id: dict[uuid.UUID, Job],
        result: InitialPlanningResult,
    ) -> None:
        unassigned_ids = [item.job_id for item in result.unassigned]
        all_result_ids = assigned_ids + unassigned_ids
        if len(all_result_ids) != len(set(all_result_ids)):
            raise AlgorithmAuditError("Заявка встретилась в результате больше одного раза")
        if set(all_result_ids) != set(jobs_by_id):
            raise AlgorithmAuditError("Результат не покрывает полный входной пул заявок")
        if result.metrics.assigned_requests_count != len(assigned_ids):
            raise AlgorithmAuditError("Метрика assigned не совпадает с маршрутами")
        if result.metrics.unassigned_requests_count != len(unassigned_ids):
            raise AlgorithmAuditError("Метрика unassigned не совпадает с результатом")

    @staticmethod
    def _audit_plan_metrics(
        planning_input: InitialPlanningInput,
        result: InitialPlanningResult,
        assigned_ids: list[uuid.UUID],
    ) -> None:
        expected_values = (
            len(assigned_ids),
            sum(engineer.is_available for engineer in planning_input.engineers),
            len(result.routes),
            sum(route.service_minutes for route in result.routes),
            sum(route.travel_minutes for route in result.routes),
            sum((route.distance_km for route in result.routes), start=Decimal("0")),
        )
        actual_values = (
            result.metrics.assigned_requests_count,
            result.metrics.engineers_available_count,
            result.metrics.engineers_used_count,
            result.metrics.total_service_minutes,
            result.metrics.total_travel_minutes,
            result.metrics.total_mileage_km,
        )
        if actual_values != expected_values:
            raise AlgorithmAuditError("Агрегаты плана не совпадают с маршрутами")
