import uuid
from decimal import Decimal

from src.core.algorithm.distribution import DistributionPlanner
from src.core.algorithm.dto import AlgorithmPlanResult, EngineerContext, Job
from src.core.algorithm.enums import DistributionMode
from src.core.algorithm.exc import MissingCoordinatesError
from src.core.algorithm.strategies import LayeredExactStateGraph
from src.core.db.dto import PlanCreateDTO, PlanStopCreateDTO, PlanUnassignedRequestCreateDTO
from src.core.db.enums import PlanKind, Region
from src.core.db.models import Engineer, Request
from src.core.db.uow import UnitOfWork
from src.core.routing import RoutingPoint, RoutingService


class AlgorithmService:
    """Строит и сохраняет план распределения заявок по инженерам одного округа.

    Вызывается после того, как `Request`/`Engineer` уже сохранены в БД (см.
    `PlanningService.import_initial_data`) — грузит их по `upload_id`,
    строит матрицу времени/расстояния через `RoutingService` одним запросом
    на весь округ, распределяет заявки через `DistributionPlanner`
    единственной подключённой сейчас стратегией (`LayeredExactStateGraph` —
    самая быстрая из протестированных, см. `docs/ALGORITHM.md`), сохраняет
    результат как новый `Plan`.
    """

    def __init__(self, uow: UnitOfWork, routing: RoutingService) -> None:
        self._uow = uow
        self._routing = routing
        self._planner = DistributionPlanner(LayeredExactStateGraph())

    async def plan_initial(
        self, upload_id: uuid.UUID, region: Region, mode: DistributionMode
    ) -> AlgorithmPlanResult:
        requests = await self._uow.requests.get_by_upload_id(upload_id)
        engineers = await self._uow.engineers.get_by_upload_id(upload_id)

        jobs = [self._to_job(request) for request in requests]
        engineer_contexts = [self._to_engineer_context(engineer) for engineer in engineers]

        points = [
            RoutingPoint(
                id=engineer.id,
                latitude=engineer.start_latitude,
                longitude=engineer.start_longitude,
            )
            for engineer in engineer_contexts
        ] + [
            RoutingPoint(id=job.id, latitude=job.latitude, longitude=job.longitude) for job in jobs
        ]
        travel_matrix = await self._routing.build_matrix(points)

        result = self._planner.assign(engineer_contexts, jobs, travel_matrix, mode)

        total_mileage_km = sum(
            (stop.distance_km for route in result.routes for stop in route.stops),
            start=Decimal("0"),
        )
        plan_id = self._uow.plans.create(
            PlanCreateDTO(
                region=region,
                upload_id=upload_id,
                kind=PlanKind.INITIAL,
                is_baseline=False,
                based_on_plan_id=None,
                triggered_by_event_id=None,
                total_mileage_km=total_mileage_km,
                engineers_used_count=len(result.routes),
            )
        )

        self._uow.plan_stops.add_many(
            [
                PlanStopCreateDTO(
                    plan_id=plan_id,
                    engineer_id=route.engineer_id,
                    request_id=stop.request_id,
                    sequence_number=stop.sequence_number,
                    planned_arrival=stop.arrival,
                    planned_start=stop.start,
                    planned_finish=stop.finish,
                    travel_minutes=stop.travel_minutes,
                    distance_km=stop.distance_km,
                    is_locked=False,
                )
                for route in result.routes
                for stop in route.stops
            ]
        )
        self._uow.plan_unassigned_requests.add_many(
            [
                PlanUnassignedRequestCreateDTO(
                    plan_id=plan_id, request_id=item.job_id, reason=item.reason
                )
                for item in result.unassigned
            ]
        )
        await self._uow.commit()

        return AlgorithmPlanResult(
            plan_id=plan_id,
            region=region,
            engineers_used_count=len(result.routes),
            total_mileage_km=total_mileage_km,
            assigned_requests_count=sum(len(route.stops) for route in result.routes),
            unassigned_requests_count=len(result.unassigned),
        )

    @staticmethod
    def _to_job(request: Request) -> Job:
        if request.latitude is None or request.longitude is None:
            raise MissingCoordinatesError(f"У заявки {request.id} нет координат")
        return Job(
            id=request.id,
            latitude=request.latitude,
            longitude=request.longitude,
            window_start=request.window_start,
            window_end=request.window_end,
            service_minutes=request.norm_minutes_without_travel,
            priority=request.priority,
            required_skill=request.required_skill,
            required_vehicle_type=request.required_vehicle_type,
        )

    @staticmethod
    def _to_engineer_context(engineer: Engineer) -> EngineerContext:
        if engineer.start_point_latitude is None or engineer.start_point_longitude is None:
            raise MissingCoordinatesError(f"У инженера {engineer.id} нет координат старта")
        return EngineerContext(
            id=engineer.id,
            start_latitude=engineer.start_point_latitude,
            start_longitude=engineer.start_point_longitude,
            shift_start=engineer.shift_start,
            shift_end=engineer.shift_end,
            skills=frozenset(skill.skill for skill in engineer.skills),
            vehicle_type=engineer.vehicle_type,
        )
