import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from src.config import cfg
from src.core.algorithm.dto import (
    Engineer,
    EngineerSnapshot,
    InitialPlanningDraft,
    InitialPlanningInput,
    InitialPlanningSnapshot,
    Job,
    LayerMatrix,
    LayerMatrixRequest,
    LayerTravelMatrix,
    PlanningLayer,
    RequestSnapshot,
    RoutePoint,
)
from src.core.algorithm.exc import AlgorithmInputError, MissingCoordinatesError
from src.core.db.enums import RequestPriority


class InitialInputNormalizer:
    """Превращает snapshot округа в эффективные окна и запросы матриц слоёв."""

    def prepare(self, snapshot: InitialPlanningSnapshot) -> InitialPlanningDraft:
        operational_start = datetime.combine(
            snapshot.planning_date, cfg.planning.default_shift_start
        )
        jobs = tuple(self._to_job(request, operational_start) for request in snapshot.requests)
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
    def _to_job(request: RequestSnapshot, operational_start: datetime) -> Job:
        """Нормализует окно начала работ; авария initial получает SLA 120 минут."""

        if request.latitude is None or request.longitude is None:
            raise MissingCoordinatesError(f"У заявки {request.id} нет координат")
        is_emergency = request.priority == RequestPriority.EMERGENCY
        release_at = operational_start if is_emergency else request.window_start
        latest_start_at = (
            operational_start + timedelta(minutes=cfg.algorithm.emergency_response_minutes)
            if is_emergency
            else request.window_end
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
            available_from=max(engineer.shift_start, cutoff_at),
            shift_end=engineer.shift_end,
            skills=engineer.skills,
            vehicle_type=engineer.vehicle_type,
            is_available=engineer.is_available,
        )
