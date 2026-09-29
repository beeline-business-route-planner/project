import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from src.core.algorithm.dto import (
    Engineer,
    InitialPlanningInput,
    Job,
    KnownSolution,
    ManualIssue,
    PlanningLayer,
    Stop,
)
from src.core.algorithm.enums import ManualIssueCode
from src.core.algorithm.exc import AlgorithmInputError
from src.core.algorithm.rules import PlanningRules


class ScheduleMaterializer:
    """Превращает порядок заявок в точные arrival/start/finish."""

    def feasible_routes(
        self,
        planning_input: InitialPlanningInput,
        solution: KnownSolution,
        layers_by_request: dict[uuid.UUID, PlanningLayer],
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]] | None:
        """Возвращает допустимые на этом входе маршруты известного решения.

        Маршрут, который ссылается на неизвестную заявку или инженера, нарушает навык,
        транспорт или доступность либо не материализуется, отбрасывается целиком; его
        заявки становятся неназначенными в этом решении. Остальные маршруты остаются:
        частичное известное решение всё ещё допустимо. Повторное назначение заявки или
        инженера означает испорченное решение, и тогда оно отвергается полностью.
        """

        jobs_by_id = {job.id: job for job in planning_input.jobs}
        engineers_by_id = {engineer.id: engineer for engineer in planning_input.engineers}
        request_ids = [request_id for route in solution.routes for request_id in route.request_ids]
        engineer_ids = [route.engineer_id for route in solution.routes]
        if len(request_ids) != len(set(request_ids)) or len(engineer_ids) != len(set(engineer_ids)):
            return None
        routes: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {}
        for route in solution.routes:
            engineer = engineers_by_id.get(route.engineer_id)
            if (
                engineer is None
                or not route.request_ids
                or any(
                    request_id not in jobs_by_id
                    or not PlanningRules.eligible(engineer, jobs_by_id[request_id])
                    for request_id in route.request_ids
                )
                or self.materialize(
                    engineer,
                    route.request_ids,
                    jobs_by_id,
                    layers_by_request,
                    planning_input.calculation_cutoff_at,
                )
                is None
            ):
                continue
            routes[route.engineer_id] = route.request_ids
        return routes

    def materialize(
        self,
        engineer: Engineer,
        request_ids: Sequence[uuid.UUID],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_at: datetime,
    ) -> tuple[Stop, ...] | None:
        previous_id = engineer.id
        previous_finish = max(engineer.available_from, cutoff_at)
        previous_window_start: datetime | None = None
        stops: list[Stop] = []
        for sequence_number, request_id in enumerate(request_ids, start=1):
            job = jobs_by_id[request_id]
            layer = layers_by_request[request_id]
            # Переход в более ранний слой невыполним по времени, и матрица слоя его не содержит.
            if previous_window_start is not None and layer.window_start < previous_window_start:
                return None
            previous_window_start = layer.window_start
            matching_matrices = [
                item.travel_matrix
                for item in layer.matrices
                if item.vehicle_type == engineer.vehicle_type
            ]
            if len(matching_matrices) != 1:
                raise AlgorithmInputError(
                    f"Для слоя заявки {request_id} нет единственной матрицы "
                    f"транспорта {engineer.vehicle_type}"
                )
            travel_matrix = matching_matrices[0]
            try:
                travel_minutes = travel_matrix.minutes(previous_id, request_id)
                distance_km = travel_matrix.kilometers(previous_id, request_id)
            except (KeyError, IndexError) as exc:
                raise AlgorithmInputError(
                    f"Матрица слоя не покрывает переход {previous_id} -> {request_id}"
                ) from exc
            if travel_minutes is None or distance_km is None:
                return None
            arrival = previous_finish + timedelta(minutes=travel_minutes)
            start = max(arrival, job.release_at, cutoff_at)
            finish = start + timedelta(minutes=job.service_minutes)
            if start > job.latest_start_at or finish > engineer.shift_end:
                return None
            stops.append(
                Stop(
                    request_id=request_id,
                    sequence_number=sequence_number,
                    arrival=arrival,
                    start=start,
                    finish=finish,
                    travel_minutes=travel_minutes,
                    distance_km=PlanningRules.stop_distance(distance_km),
                )
            )
            previous_id = request_id
            previous_finish = finish
        return tuple(stops)

    def diagnose(
        self,
        engineer: Engineer,
        request_ids: Sequence[uuid.UUID],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_at: datetime,
    ) -> tuple[tuple[Stop, ...], tuple[ManualIssue, ...]]:
        """Разбирает ручной порядок так же, как `materialize`, но не останавливается.

        Каждое нарушение записывается на свою заявку, расчёт идёт дальше с фактическим
        (пусть и недопустимым) временем, чтобы диспетчер увидел все проблемы маршрута и
        примерное расписание сразу. Заявку без перехода (порядок слоёв, нет маршрута)
        бригада «выполняет» без дороги — дальше время остаётся оценкой.
        """

        previous_id = engineer.id
        previous_finish = max(engineer.available_from, cutoff_at)
        previous_window_start: datetime | None = None
        stops: list[Stop] = []
        issues: list[ManualIssue] = []
        for sequence_number, request_id in enumerate(request_ids, start=1):
            job = jobs_by_id[request_id]
            layer = layers_by_request[request_id]
            if previous_window_start is not None and layer.window_start < previous_window_start:
                issues.append(ManualIssue(request_id, engineer.id, ManualIssueCode.WINDOW_ORDER))
                previous_finish = max(previous_finish, job.release_at) + timedelta(
                    minutes=job.service_minutes
                )
                previous_id = request_id
                continue
            previous_window_start = layer.window_start
            matching_matrices = [
                item.travel_matrix
                for item in layer.matrices
                if item.vehicle_type == engineer.vehicle_type
            ]
            travel_minutes: int | None = None
            distance_km = None
            if len(matching_matrices) == 1:
                try:
                    travel_minutes = matching_matrices[0].minutes(previous_id, request_id)
                    distance_km = matching_matrices[0].kilometers(previous_id, request_id)
                except KeyError, IndexError:
                    travel_minutes = None
            if travel_minutes is None or distance_km is None:
                issues.append(ManualIssue(request_id, engineer.id, ManualIssueCode.NO_ROUTE))
                previous_finish = max(previous_finish, job.release_at, cutoff_at) + timedelta(
                    minutes=job.service_minutes
                )
                previous_id = request_id
                continue
            arrival = previous_finish + timedelta(minutes=travel_minutes)
            start = max(arrival, job.release_at, cutoff_at)
            finish = start + timedelta(minutes=job.service_minutes)
            if start > job.latest_start_at:
                # Окно закрылось ещё до расчёта — это не опоздание бригады, а прошедшее время.
                code = (
                    ManualIssueCode.WINDOW_PASSED
                    if cutoff_at > job.latest_start_at
                    else ManualIssueCode.LATE
                )
                issues.append(
                    ManualIssue(request_id, engineer.id, code, at=start, limit=job.latest_start_at)
                )
            if finish > engineer.shift_end:
                issues.append(
                    ManualIssue(
                        request_id,
                        engineer.id,
                        ManualIssueCode.SHIFT_END,
                        at=finish,
                        limit=engineer.shift_end,
                    )
                )
            stops.append(
                Stop(
                    request_id=request_id,
                    sequence_number=sequence_number,
                    arrival=arrival,
                    start=start,
                    finish=finish,
                    travel_minutes=travel_minutes,
                    distance_km=PlanningRules.stop_distance(distance_km),
                )
            )
            previous_id = request_id
            previous_finish = finish
        return tuple(stops), tuple(issues)
