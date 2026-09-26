import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from src.config import cfg
from src.core.algorithm.dto import (
    BasePlanStop,
    Engineer,
    EngineerSnapshot,
    InitialPlanningDraft,
    InitialPlanningInput,
    InitialPlanningSnapshot,
    Job,
    KnownRoute,
    KnownSolution,
    LayerMatrix,
    LayerMatrixRequest,
    LayerTravelMatrix,
    PlanningLayer,
    ReplanDraft,
    ReplanInput,
    ReplanSnapshot,
    RequestSnapshot,
    RoutePoint,
)
from src.core.algorithm.exc import AlgorithmInputError, MissingCoordinatesError
from src.core.db.enums import RequestPriority, RequestStatus
from src.core.utils.plan_time import latest_departure_at


class InitialInputNormalizer:
    """Превращает snapshot округа в эффективные окна и запросы матриц слоёв."""

    def prepare(self, snapshot: InitialPlanningSnapshot) -> InitialPlanningDraft:
        operational_start = datetime.combine(
            snapshot.planning_date, cfg.planning.default_shift_start
        )
        operational_end = datetime.combine(snapshot.planning_date, cfg.planning.default_shift_end)
        jobs = tuple(
            self._to_job(request, operational_start, operational_end)
            for request in snapshot.requests
        )
        engineers = tuple(
            self._to_engineer(engineer, snapshot.calculation_cutoff_at)
            for engineer in snapshot.engineers
        )
        available_engineers = tuple(engineer for engineer in engineers if engineer.is_available)
        points = tuple(
            RoutePoint(
                id=engineer.id,
                latitude=engineer.start_latitude,
                longitude=engineer.start_longitude,
            )
            for engineer in available_engineers
        ) + tuple(
            RoutePoint(id=job.id, latitude=job.latitude, longitude=job.longitude) for job in jobs
        )
        return InitialPlanningDraft(
            region=snapshot.region,
            planning_date=snapshot.planning_date,
            calculation_cutoff_at=snapshot.calculation_cutoff_at,
            mode=snapshot.mode,
            jobs=jobs,
            engineers=engineers,
            points=points,
            matrix_requests=self._matrix_requests(jobs, available_engineers),
        )

    def build(
        self,
        draft: InitialPlanningDraft,
        matrices: Sequence[LayerMatrix],
    ) -> InitialPlanningInput:
        matrices_by_request = {matrix.request: matrix.travel_matrix for matrix in matrices}
        if len(matrices_by_request) != len(matrices) or set(matrices_by_request) != set(
            draft.matrix_requests
        ):
            raise AlgorithmInputError("Матрицы должны ровно один раз покрывать запросы черновика")
        jobs_by_window: dict[tuple[datetime, datetime], list[Job]] = {}
        for job in draft.jobs:
            jobs_by_window.setdefault((job.release_at, job.latest_start_at), []).append(job)
        layers = tuple(
            PlanningLayer(
                window_start=window_start,
                window_end=window_end,
                traffic_reference_at=window_start + (window_end - window_start) / 2,
                request_ids=frozenset(job.id for job in layer_jobs),
                matrices=tuple(
                    LayerTravelMatrix(
                        vehicle_type=request.vehicle_type,
                        travel_matrix=matrices_by_request[request],
                    )
                    for request in draft.matrix_requests
                    if (request.window_start, request.window_end) == (window_start, window_end)
                ),
            )
            for (window_start, window_end), layer_jobs in sorted(jobs_by_window.items())
        )
        return InitialPlanningInput(
            region=draft.region,
            planning_date=draft.planning_date,
            calculation_cutoff_at=draft.calculation_cutoff_at,
            mode=draft.mode,
            jobs=draft.jobs,
            engineers=draft.engineers,
            layers=layers,
        )

    @staticmethod
    def _matrix_requests(
        jobs: tuple[Job, ...],
        available_engineers: tuple[Engineer, ...],
    ) -> tuple[LayerMatrixRequest, ...]:
        """Описывает одну матрицу на слой и тип транспорта.

        Sources — старты инженеров этого транспорта и заявки текущего и всех предыдущих
        слоёв: до запуска графа неизвестно, какие хвосты останутся во frontier.
        Будущие слои не включаются.
        """

        jobs_by_window: dict[tuple[datetime, datetime], list[Job]] = {}
        for job in jobs:
            jobs_by_window.setdefault((job.release_at, job.latest_start_at), []).append(job)
        vehicle_types = sorted(
            {engineer.vehicle_type for engineer in available_engineers},
            key=lambda item: item.value,
        )
        requests: list[LayerMatrixRequest] = []
        previous_job_ids: set[uuid.UUID] = set()
        for (window_start, window_end), layer_jobs in sorted(jobs_by_window.items()):
            for vehicle_type in vehicle_types:
                target_ids = frozenset(
                    job.id
                    for job in layer_jobs
                    if job.required_vehicle_type is None
                    or job.required_vehicle_type == vehicle_type
                )
                if not target_ids:
                    continue
                engineer_ids = {
                    engineer.id
                    for engineer in available_engineers
                    if engineer.vehicle_type == vehicle_type
                }
                requests.append(
                    LayerMatrixRequest(
                        window_start=window_start,
                        window_end=window_end,
                        traffic_reference_at=window_start + (window_end - window_start) / 2,
                        vehicle_type=vehicle_type,
                        source_ids=frozenset(engineer_ids | previous_job_ids | target_ids),
                        target_ids=target_ids,
                    )
                )
            previous_job_ids.update(job.id for job in layer_jobs)
        return tuple(requests)

    @staticmethod
    def _to_job(
        request: RequestSnapshot,
        operational_start: datetime,
        operational_end: datetime,
    ) -> Job:
        """Нормализует окно начала работ с SLA аварии 120 минут.

        Техническое окно аварии на весь день (`00:01–23:59`) отсчитывается от начала
        операционного дня. Авария с обычным клиентским окном не может начаться раньше
        этого окна, поэтому SLA отсчитывается от его начала и не выходит за его конец.
        """

        if request.latitude is None or request.longitude is None:
            raise MissingCoordinatesError(f"У заявки {request.id} нет координат")
        is_emergency = request.priority == RequestPriority.EMERGENCY
        release_at = request.window_start
        latest_start_at = request.window_end
        if is_emergency:
            response = timedelta(minutes=cfg.algorithm.emergency_response_minutes)
            covers_whole_day = (
                request.window_start <= operational_start and request.window_end >= operational_end
            )
            release_at = operational_start if covers_whole_day else request.window_start
            latest_start_at = (
                release_at + response
                if covers_whole_day
                else min(request.window_end, release_at + response)
            )
        return Job(
            id=request.id,
            latitude=request.latitude,
            longitude=request.longitude,
            source_window_start=request.window_start,
            source_window_end=request.window_end,
            release_at=release_at,
            latest_start_at=latest_start_at,
            service_minutes=request.service_minutes,
            priority=request.priority,
            required_skill=request.required_skill,
            required_vehicle_type=request.required_vehicle_type,
            is_emergency=is_emergency,
        )

    @staticmethod
    def _to_engineer(engineer: EngineerSnapshot, cutoff_at: datetime) -> Engineer:
        if engineer.start_latitude is None or engineer.start_longitude is None:
            raise MissingCoordinatesError(f"У инженера {engineer.id} нет координат старта")
        return Engineer(
            id=engineer.id,
            start_latitude=engineer.start_latitude,
            start_longitude=engineer.start_longitude,
            shift_start=engineer.shift_start,
            available_from=max(engineer.shift_start, cutoff_at, engineer.ready_at or cutoff_at),
            shift_end=engineer.shift_end,
            skills=engineer.skills,
            vehicle_type=engineer.vehicle_type,
            is_available=engineer.is_available,
        )


class ReplanNormalizer:
    """Делит утверждённый план на неизменяемую историю и вход для пересчёта будущего хвоста.

    Остановка фиксируется, если заявка уже в пути, в работе или выполнена либо если
    инженер к cutoff уже должен был выехать к ней даже при самом позднем выезде
    (`start - travel`). Вместе с ней фиксируются все более ранние остановки того же
    инженера: прожитая история — всегда префикс маршрута. Хвост инженера начинается из
    точки последней зафиксированной остановки не раньше её окончания и cutoff; у инженера
    без истории — из его стартовой точки. Отменённая незафиксированная заявка в хвост не
    попадает. Недоступный инженер сохраняет историю и не получает будущих остановок.
    """

    def __init__(self) -> None:
        self._initial = InitialInputNormalizer()

    def prepare(self, snapshot: ReplanSnapshot) -> ReplanDraft:
        requests_by_id = {request.id: request for request in snapshot.requests}
        locked_stops = self._locked_stops(snapshot, requests_by_id)
        locked_ids = {stop.request_id for stop in locked_stops}
        cancelled_ids = frozenset(
            request.id
            for request in snapshot.requests
            if request.status == RequestStatus.CANCELLED and request.id not in locked_ids
        )
        last_locked: dict[uuid.UUID, BasePlanStop] = {}
        for stop in locked_stops:
            last_locked[stop.engineer_id] = stop
        tail_engineers = tuple(
            self._tail_engineer(engineer, last_locked.get(engineer.id), requests_by_id)
            for engineer in snapshot.engineers
        )
        tail = self._initial.prepare(
            InitialPlanningSnapshot(
                region=snapshot.region,
                planning_date=snapshot.planning_date,
                calculation_cutoff_at=snapshot.calculation_cutoff_at,
                mode=snapshot.mode,
                requests=tuple(
                    request
                    for request in snapshot.requests
                    if request.id not in locked_ids and request.id not in cancelled_ids
                ),
                engineers=tail_engineers,
            )
        )
        return ReplanDraft(
            snapshot=snapshot,
            locked_stops=locked_stops,
            cancelled_request_ids=cancelled_ids,
            tail=tail,
        )

    def build(self, draft: ReplanDraft, matrices: Sequence[LayerMatrix]) -> ReplanInput:
        """Собирает вход хвоста; будущая часть текущего плана передаётся известным решением.

        Если с момента утверждения ничего не изменилось, этот хвост остаётся допустимым,
        и стратегия не вернёт план хуже текущего.
        """

        locked_ids = {stop.request_id for stop in draft.locked_stops}
        future_by_engineer: dict[uuid.UUID, list[BasePlanStop]] = {}
        for stop in draft.snapshot.base_stops:
            if stop.request_id not in locked_ids:
                future_by_engineer.setdefault(stop.engineer_id, []).append(stop)
        current_future = KnownSolution(
            routes=tuple(
                KnownRoute(
                    engineer_id=engineer_id,
                    request_ids=tuple(
                        stop.request_id
                        for stop in sorted(stops, key=lambda item: item.sequence_number)
                    ),
                )
                for engineer_id, stops in sorted(
                    future_by_engineer.items(), key=lambda item: item[0].int
                )
            )
        )
        return ReplanInput(
            snapshot=draft.snapshot,
            locked_stops=draft.locked_stops,
            cancelled_request_ids=draft.cancelled_request_ids,
            tail=replace(
                self._initial.build(draft.tail, matrices), known_solutions=(current_future,)
            ),
        )

    @staticmethod
    def _locked_stops(
        snapshot: ReplanSnapshot,
        requests_by_id: dict[uuid.UUID, RequestSnapshot],
    ) -> tuple[BasePlanStop, ...]:
        """Выбирает префикс маршрута каждого инженера до последней прожитой остановки.

        Raises:
            AlgorithmInputError: если остановка ссылается на неизвестную заявку/инженера,
                последовательность маршрута прерывается или начатая заявка не в плане.
        """

        engineer_ids = {engineer.id for engineer in snapshot.engineers}
        started_statuses = {RequestStatus.ON_THE_WAY, RequestStatus.IN_PROGRESS, RequestStatus.DONE}
        stops_by_engineer: dict[uuid.UUID, list[BasePlanStop]] = {}
        for stop in snapshot.base_stops:
            if stop.request_id not in requests_by_id or stop.engineer_id not in engineer_ids:
                raise AlgorithmInputError("Остановка базового плана вне snapshot")
            stops_by_engineer.setdefault(stop.engineer_id, []).append(stop)
        locked: list[BasePlanStop] = []
        for engineer_id in sorted(stops_by_engineer, key=lambda item: item.int):
            stops = sorted(stops_by_engineer[engineer_id], key=lambda stop: stop.sequence_number)
            if [stop.sequence_number for stop in stops] != list(range(1, len(stops) + 1)):
                raise AlgorithmInputError("Последовательность базового маршрута прерывается")
            lived_count = max(
                (
                    index + 1
                    for index, stop in enumerate(stops)
                    if latest_departure_at(stop.start, stop.travel_minutes)
                    < snapshot.calculation_cutoff_at
                    or requests_by_id[stop.request_id].status in started_statuses
                ),
                default=0,
            )
            locked.extend(stops[:lived_count])
        planned_ids = {stop.request_id for stop in snapshot.base_stops}
        if any(
            request.status in started_statuses and request.id not in planned_ids
            for request in snapshot.requests
        ):
            raise AlgorithmInputError("Начатая или выполненная заявка отсутствует в базовом плане")
        return tuple(locked)

    @staticmethod
    def _tail_engineer(
        engineer: EngineerSnapshot,
        last_locked: BasePlanStop | None,
        requests_by_id: dict[uuid.UUID, RequestSnapshot],
    ) -> EngineerSnapshot:
        if last_locked is None:
            return engineer
        request = requests_by_id[last_locked.request_id]
        return replace(
            engineer,
            start_latitude=request.latitude,
            start_longitude=request.longitude,
            ready_at=last_locked.finish,
        )
