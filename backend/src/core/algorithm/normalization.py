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
    ReplanEvent,
    ReplanInput,
    ReplanSnapshot,
    RequestSnapshot,
    RoutePoint,
)
from src.core.algorithm.exc import AlgorithmInputError, MissingCoordinatesError
from src.core.db.enums import ReplanningEventType, RequestPriority, RequestStatus


class InitialInputNormalizer:
    """Превращает snapshot округа в эффективные окна и запросы матриц слоёв."""

    def prepare(self, snapshot: InitialPlanningSnapshot) -> InitialPlanningDraft:
        operational_start = datetime.combine(
            snapshot.planning_date, cfg.planning.default_shift_start
        )
        jobs = tuple(
            self._to_job(request, operational_start, snapshot.calculation_cutoff_at)
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

        Sources — старты инженеров этого транспорта и заявки всех слоёв, начинающихся не
        позже текущего: до запуска графа неизвестно, какие хвосты останутся во frontier, а
        переход между слоями с одинаковым началом окна допустим в обе стороны.
        Слои с более поздним началом не включаются.
        """

        jobs_by_window: dict[tuple[datetime, datetime], list[Job]] = {}
        for job in jobs:
            jobs_by_window.setdefault((job.release_at, job.latest_start_at), []).append(job)
        vehicle_types = sorted(
            {engineer.vehicle_type for engineer in available_engineers},
            key=lambda item: item.value,
        )
        requests: list[LayerMatrixRequest] = []
        for (window_start, window_end), layer_jobs in sorted(jobs_by_window.items()):
            earlier_job_ids = {job.id for job in jobs if job.release_at <= window_start}
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
                        source_ids=frozenset(engineer_ids | earlier_job_ids | target_ids),
                        target_ids=target_ids,
                    )
                )
        return tuple(requests)

    @staticmethod
    def _to_job(
        request: RequestSnapshot,
        operational_start: datetime,
        cutoff_at: datetime,
    ) -> Job:
        """Нормализует окно начала работ с SLA аварии 120 минут.

        SLA аварии отсчитывается от момента её поступления, но не раньше начала
        операционного дня и не раньше клиентского окна: `release = max(окно, поступление)`,
        `latest = min(конец окна, release + 120)`. Техническое окно на весь день
        (`00:01–23:59`) — частный случай этого правила. Если к cutoff SLA уже истёк, а заявка
        всё ещё в пересчитываемом пуле, отсчёт начинается заново от cutoff: аварию нужно
        выполнить как можно раньше, а не молча отбросить. Клиентское окно при этом не
        расширяется: если отсчёт начинается после его конца, окно остаётся исходным, и
        авария честно не назначается.
        """

        if request.latitude is None or request.longitude is None:
            raise MissingCoordinatesError(f"У заявки {request.id} нет координат")
        is_emergency = request.priority == RequestPriority.EMERGENCY
        release_at = request.window_start
        latest_start_at = request.window_end
        if is_emergency:
            response = timedelta(minutes=cfg.algorithm.emergency_response_minutes)
            sla_start = max(
                request.window_start, request.received_at or cutoff_at, operational_start
            )
            if sla_start + response < cutoff_at:
                sla_start = cutoff_at
            if sla_start <= request.window_end:
                release_at = sla_start
                latest_start_at = min(request.window_end, sla_start + response)
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
            history_service_minutes=engineer.history_service_minutes,
        )


class ReplanNormalizer:
    """Делит утверждённый план на неизменяемую историю и вход для пересчёта будущего хвоста.

    Остановка прожита, если заявка в работе или выполнена, в пути у доступного инженера
    либо её плановое начало раньше cutoff. Отменённая заявка и заявка «в пути» у выбывшего
    инженера сами прожитыми не считаются: в конце истории они снимаются с маршрута и
    отменённая исчезает, а «в пути» уходит в пересчёт; в середине истории остаются как есть.
    Фиксируется префикс маршрута до последней прожитой остановки. Хвост инженера
    начинается из точки последней зафиксированной остановки не раньше её окончания и
    cutoff; у инженера без истории или вернувшегося в строй после неё — из его стартовой
    точки. Недоступный инженер сохраняет историю и не получает будущих остановок. Минуты
    истории передаются хвосту, чтобы цель режима считалась за весь день.
    """

    def __init__(self) -> None:
        self._initial = InitialInputNormalizer()

    def prepare_event(self, snapshot: ReplanSnapshot, event: ReplanEvent) -> ReplanDraft:
        """Применяет одно событие к snapshot и готовит replan с ним.

        Raises:
            AlgorithmInputError: если событие не согласовано со snapshot: время события
                позже cutoff, цель не найдена, повторяется или переход невозможен.
        """

        return replace(self.prepare(self._apply_event(snapshot, event)), event=event)

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
        history_minutes: dict[uuid.UUID, int] = {}
        for stop in locked_stops:
            last_locked[stop.engineer_id] = stop
            history_minutes[stop.engineer_id] = (
                history_minutes.get(stop.engineer_id, 0)
                + requests_by_id[stop.request_id].service_minutes
            )
        tail_engineers = tuple(
            self._tail_engineer(
                engineer,
                last_locked.get(engineer.id),
                history_minutes.get(engineer.id, 0),
                requests_by_id,
            )
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

        Из неё убраны заявки, которых больше нет в пуле хвоста, и маршруты недоступных
        инженеров: снятая событием часть не обесценивает остальной текущий план.
        """

        tail_job_ids = {job.id for job in draft.tail.jobs}
        available_ids = {engineer.id for engineer in draft.tail.engineers if engineer.is_available}
        future_by_engineer: dict[uuid.UUID, list[BasePlanStop]] = {}
        for stop in draft.snapshot.base_stops:
            if stop.request_id in tail_job_ids and stop.engineer_id in available_ids:
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
            event=draft.event,
        )

    @staticmethod
    def _apply_event(snapshot: ReplanSnapshot, event: ReplanEvent) -> ReplanSnapshot:
        if event.occurred_at > snapshot.calculation_cutoff_at:
            raise AlgorithmInputError("Событие не может произойти позже cutoff расчёта")
        request_ids = {request.id for request in snapshot.requests}
        match event.event_type:
            case ReplanningEventType.URGENT_REQUEST:
                urgent = event.urgent_request
                if urgent is None or urgent.id in request_ids:
                    raise AlgorithmInputError("Срочная заявка отсутствует или уже есть в плане")
                return replace(
                    snapshot,
                    requests=(*snapshot.requests, replace(urgent, received_at=event.occurred_at)),
                )
            case ReplanningEventType.REQUEST_CANCELLED:
                target = next(
                    (item for item in snapshot.requests if item.id == event.request_id), None
                )
                if target is None or target.status in {
                    RequestStatus.IN_PROGRESS,
                    RequestStatus.DONE,
                    RequestStatus.CANCELLED,
                }:
                    raise AlgorithmInputError("Отменить можно только ещё не начатую заявку")
                return replace(
                    snapshot,
                    requests=tuple(
                        replace(item, status=RequestStatus.CANCELLED) if item is target else item
                        for item in snapshot.requests
                    ),
                )
            case ReplanningEventType.ENGINEER_UNAVAILABLE | ReplanningEventType.ENGINEER_AVAILABLE:
                returns = event.event_type == ReplanningEventType.ENGINEER_AVAILABLE
                engineer = next(
                    (item for item in snapshot.engineers if item.id == event.engineer_id), None
                )
                if engineer is None or engineer.is_available == returns:
                    raise AlgorithmInputError("Недопустимый переход доступности инженера")
                changed = replace(
                    engineer,
                    is_available=returns,
                    returned_at=event.occurred_at if returns else engineer.returned_at,
                )
                return replace(
                    snapshot,
                    engineers=tuple(
                        changed if item is engineer else item for item in snapshot.engineers
                    ),
                )
        raise AlgorithmInputError(f"Неизвестный тип события: {event.event_type}")

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

        available_ids = {engineer.id for engineer in snapshot.engineers if engineer.is_available}
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
                    if ReplanNormalizer._lived(
                        stop,
                        requests_by_id[stop.request_id].status,
                        engineer_id in available_ids,
                        snapshot.calculation_cutoff_at,
                    )
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
    def _lived(
        stop: BasePlanStop,
        status: RequestStatus,
        engineer_available: bool,
        cutoff_at: datetime,
    ) -> bool:
        match status:
            case RequestStatus.IN_PROGRESS | RequestStatus.DONE:
                return True
            case RequestStatus.ON_THE_WAY:
                return engineer_available
            case RequestStatus.CANCELLED:
                return False
        return stop.start < cutoff_at

    @staticmethod
    def _tail_engineer(
        engineer: EngineerSnapshot,
        last_locked: BasePlanStop | None,
        history_service_minutes: int,
        requests_by_id: dict[uuid.UUID, RequestSnapshot],
    ) -> EngineerSnapshot:
        if last_locked is None or (
            engineer.returned_at is not None and last_locked.finish <= engineer.returned_at
        ):
            return replace(
                engineer,
                ready_at=engineer.returned_at,
                history_service_minutes=history_service_minutes,
            )
        request = requests_by_id[last_locked.request_id]
        return replace(
            engineer,
            start_latitude=request.latitude,
            start_longitude=request.longitude,
            ready_at=last_locked.finish,
            history_service_minutes=history_service_minutes,
        )
