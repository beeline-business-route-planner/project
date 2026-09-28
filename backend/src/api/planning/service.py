import asyncio
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from src.api.exc.planning import (
    PlanningAddressNotFound,
    PlanningCurrentPlanMissing,
    PlanningEngineerStateConflict,
    PlanningEventTargetMissing,
    PlanningFileCountError,
    PlanningFileValidationError,
    PlanningGeocodingUnavailable,
    PlanningInvalidRoutingResponse,
    PlanningMissingCoordinates,
    PlanningPendingEventExists,
    PlanningRegionPairError,
    PlanningRequestAlreadyCancelled,
    PlanningRequestAlreadyStarted,
    PlanningRoutingUnavailable,
    PlanningUrgentRequestExists,
    PlanningUrgentRequestInvalid,
    PlanningWrongDateError,
    RepeatedRequestError,
)
from src.api.planning.dto import (
    ApprovedEventFact,
    EventPlanningCommand,
    EventPlanningResult,
    InitialPlanningResult,
    InitialPlanSummary,
    ParsedWorkbook,
    PlanningRegionResult,
    PlanningUploadFile,
    ReplanBaseSnapshot,
    ReplanEngineerState,
    ReplanPlanningResult,
    ReplanPlanSummary,
    ReplanRegionResult,
    ReplanStop,
    ReplanUnassigned,
)
from src.api.planning.parser import PlanningWorkbookParser
from src.api.planning.utils import work_norm
from src.config import cfg
from src.core.algorithm import (
    AlgorithmService,
    AlgorithmVariant,
    BasePlanStop,
    EngineerSnapshot,
    InitialPlanningSnapshot,
    LayerMatrix,
    LayerMatrixRequest,
    MissingCoordinatesError,
    ReplanEvent,
    ReplanResult,
    ReplanSnapshot,
    RequestSnapshot,
    RoutePoint,
)
from src.core.algorithm import (
    InitialPlanningResult as AlgorithmInitialPlanningResult,
)
from src.core.db.dto import (
    BaselineResultCreateDTO,
    EngineerCreateDTO,
    EngineerDTO,
    PlanCreateDTO,
    PlanEngineerStateCreateDTO,
    PlanStopCreateDTO,
    PlanUnassignedRequestCreateDTO,
    ReplanningEventCreateDTO,
    RequestCreateDTO,
    RequestDTO,
    UploadedFileCreateDTO,
)
from src.core.db.enums import (
    ApprovalStatus,
    DistributionMode,
    PlanKind,
    PlanStrategy,
    Region,
    ReplanningEventType,
    RequestStatus,
    UnassignedReason,
)
from src.core.db.models import Engineer as EngineerModel
from src.core.db.models import Request
from src.core.db.uow import UnitOfWork
from src.core.geocoding import (
    AddressNotFoundError,
    Coordinates,
    GeocodingService,
    GeocodingUnavailableError,
)
from src.core.s3 import S3Storage, S3UnavailableError
from src.core.travel_matrix import (
    InvalidTravelMatrixResponseError,
    MatrixPoint,
    MatrixRequest,
    TravelMatrixService,
    TravelMatrixUnavailableError,
)
from src.core.utils.initial_approval import InitialApprovalPolicy

log = logging.getLogger(__name__)


class PlanningService:
    """Создаёт независимые initial- и replan-кандидаты для округов."""

    def __init__(
        self,
        uow: UnitOfWork,
        geocoding: GeocodingService,
        storage: S3Storage,
        algorithm: AlgorithmService,
        travel_matrix: TravelMatrixService,
    ) -> None:
        self._uow = uow
        self._geocoding = geocoding
        self._storage = storage
        self._algorithm = algorithm
        self._travel_matrix = travel_matrix

    async def replan(
        self,
        regions: list[Region],
        mode: DistributionMode | None,
        strategy: PlanStrategy | None,
    ) -> ReplanPlanningResult:
        """Пересчитывает округа; без явных режима и стратегии берёт их из рабочего плана."""
        results = [await self._run_replan_region(region, mode, strategy) for region in regions]
        successful = sum(item.status == "success" for item in results)
        status: Literal["success", "partial_success", "error"]
        if successful == len(results):
            status = "success"
        elif successful:
            status = "partial_success"
        else:
            status = "error"
        return ReplanPlanningResult(status=status, regions=tuple(results))

    async def _run_replan_region(
        self,
        region: Region,
        mode: DistributionMode | None,
        strategy: PlanStrategy | None,
    ) -> ReplanRegionResult:
        cutoff_at = datetime.now(ZoneInfo("Europe/Moscow")).replace(tzinfo=None)
        try:
            await self._uow.plans.lock_region_day(region, cutoff_at.date())
            base = await self.prepare_replan_base(region, cutoff_at)
            plan_mode = mode or base.mode
            plan_strategy = strategy or base.strategy
            snapshot = self._to_replan_snapshot(base, plan_mode)
            draft = self._algorithm.prepare_replan(snapshot)
            matrices = await self._layer_matrices(draft.tail.points, draft.tail.matrix_requests)
            calculated = self._algorithm.plan_replan(
                self._algorithm.build_replan_input(draft, matrices),
                AlgorithmVariant(plan_strategy.value),
            )
            plan_id = await self._persist_replan_result(base, calculated, plan_strategy)
            await self._uow.flush()
            plan = await self._uow.plans.get_by_id(plan_id)
            if plan is None:
                raise RuntimeError("Сохранённый план не найден")
            summary = ReplanPlanSummary(
                id=plan.id,
                region=plan.region,
                mode=plan.mode,
                strategy=plan.strategy,
                planning_date=plan.planning_date,
                created_at=plan.created_at,
                based_on_plan_id=base.base_plan_id,
                assigned_requests_count=plan.assigned_requests_count,
                unassigned_requests_count=plan.unassigned_requests_count,
                engineers_used_count=plan.engineers_used_count,
                total_mileage_km=plan.total_mileage_km,
            )
            await self._uow.commit()
            return ReplanRegionResult(region=region, status="success", plan_summary=summary)
        except Exception as exc:
            await self._uow.rollback()
            if isinstance(exc, PlanningCurrentPlanMissing):
                code, detail = "current_plan_missing", "Нет утверждённого рабочего плана округа"
            else:
                code, detail = self._region_error(exc)
            if code == "internal_error":
                log.exception("planning.replan_region_failed", extra={"region": region.value})
            return ReplanRegionResult(
                region=region, status="error", error_code=code, error_detail=detail
            )

    async def create_event(self, request: EventPlanningCommand) -> EventPlanningResult:
        """Создаёт событие и кандидат плана в одной транзакции округа."""
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        cutoff = now.replace(tzinfo=None)
        try:
            await self._uow.plans.lock_region_day(request.region, cutoff.date())
            base = await self.prepare_replan_base(request.region, cutoff)
            if await self._uow.replanning_events.get_pending(request.region, cutoff.date()):
                raise PlanningPendingEventExists
            snapshot = self._to_replan_snapshot(base, base.mode)
            target_id = await self._validate_and_prepare_event(request, base, cutoff)
            event_id = self._uow.replanning_events.create(
                ReplanningEventCreateDTO(
                    region=request.region,
                    planning_date=cutoff.date(),
                    event_type=request.event_type,
                    request_id=target_id
                    if request.event_type
                    in (
                        ReplanningEventType.URGENT_REQUEST,
                        ReplanningEventType.REQUEST_CANCELLED,
                    )
                    else None,
                    engineer_id=target_id
                    if request.event_type
                    in (
                        ReplanningEventType.ENGINEER_UNAVAILABLE,
                        ReplanningEventType.ENGINEER_AVAILABLE,
                    )
                    else None,
                    occurred_at=now.astimezone(UTC).replace(tzinfo=None),
                )
            )
            await self._uow.flush()
            draft = self._algorithm.prepare_event_replan(
                snapshot, await self._to_replan_event(request, target_id, cutoff)
            )
            matrices = await self._layer_matrices(draft.tail.points, draft.tail.matrix_requests)
            calculated = self._algorithm.plan_replan(
                self._algorithm.build_replan_input(draft, matrices),
                AlgorithmVariant(base.strategy.value),
            )
            availability = {item.id: item.is_available for item in draft.snapshot.engineers}
            plan_id = await self._persist_replan_result(
                base, calculated, base.strategy, event_id=event_id, availability=availability
            )
            await self._uow.flush()
            plan = await self._uow.plans.get_by_id(plan_id)
            if plan is None:
                raise RuntimeError("Сохранённый event plan не найден")
            result = EventPlanningResult(
                event_id=event_id,
                event_type=request.event_type,
                request_id=target_id if request.request_id or request.urgent_request else None,
                engineer_id=target_id if request.engineer_id else None,
                occurred_at=now.astimezone(UTC).replace(tzinfo=None),
                plan=ReplanPlanSummary(
                    id=plan.id,
                    region=plan.region,
                    mode=plan.mode,
                    strategy=plan.strategy,
                    planning_date=plan.planning_date,
                    created_at=plan.created_at,
                    based_on_plan_id=base.base_plan_id,
                    assigned_requests_count=plan.assigned_requests_count,
                    unassigned_requests_count=plan.unassigned_requests_count,
                    engineers_used_count=plan.engineers_used_count,
                    total_mileage_km=plan.total_mileage_km,
                ),
            )
            await self._uow.commit()
            return result
        except (AddressNotFoundError, GeocodingUnavailableError) as exc:
            await self._uow.rollback()
            if isinstance(exc, AddressNotFoundError):
                raise PlanningAddressNotFound from exc
            raise PlanningGeocodingUnavailable from exc
        except (
            TravelMatrixUnavailableError,
            InvalidTravelMatrixResponseError,
            MissingCoordinatesError,
        ) as exc:
            await self._uow.rollback()
            if isinstance(exc, TravelMatrixUnavailableError):
                raise PlanningRoutingUnavailable from exc
            if isinstance(exc, InvalidTravelMatrixResponseError):
                raise PlanningInvalidRoutingResponse from exc
            raise PlanningMissingCoordinates from exc
        except Exception:
            await self._uow.rollback()
            raise

    async def _validate_and_prepare_event(
        self, request: EventPlanningCommand, base: ReplanBaseSnapshot, cutoff: datetime
    ) -> uuid.UUID:
        if request.event_type == ReplanningEventType.URGENT_REQUEST:
            payload = request.urgent_request
            if payload is None:
                raise PlanningUrgentRequestInvalid
            norm = work_norm(payload.type_bk)
            if (
                int(norm.priority) != payload.priority
                or payload.priority not in (1, 2)
                or norm.total_minutes != payload.norm_minutes
                or norm.service_minutes != payload.norm_minutes_without_travel
                or norm.required_skill != payload.required_skill
                or payload.window_start.date() != base.planning_date
                or payload.window_end.date() != base.planning_date
                or payload.window_end <= cutoff
            ):
                raise PlanningUrgentRequestInvalid
            same_ids = await self._uow.requests.list_by_external_id(
                base.region, base.planning_date, payload.external_id
            )
            for existing in same_ids:
                event = await self._uow.replanning_events.get_by_request_id(existing.id)
                if event is None or event.approval_status != ApprovalStatus.REJECTED:
                    raise PlanningUrgentRequestExists
            coordinates = await self._geocoding.geocode(payload.address)
            model = Request()
            model.upload_id = None
            model.external_id = payload.external_id
            model.type_bk = payload.type_bk
            model.type_hd = payload.type_hd
            model.region = base.region
            model.district = payload.district
            model.address = payload.address
            model.latitude = coordinates.latitude
            model.longitude = coordinates.longitude
            model.connection_type = payload.connection_type
            model.is_gigabit = payload.is_gigabit
            model.window_start = payload.window_start
            model.window_end = payload.window_end
            model.norm_minutes = payload.norm_minutes
            model.norm_minutes_without_travel = payload.norm_minutes_without_travel
            model.priority = payload.priority
            model.required_skill = payload.required_skill
            model.required_vehicle_type = payload.required_vehicle_type
            model.status = RequestStatus.NOT_SENT
            model.id = uuid.uuid7()
            self._uow.requests.add(model)
            await self._uow.flush()
            return model.id

        if request.event_type == ReplanningEventType.REQUEST_CANCELLED:
            return await self._validate_cancel_target(request.request_id, base)

        target = request.engineer_id
        engineer_item = next((item for item in base.engineers if item.id == target), None)
        if (
            engineer_item is None
            or engineer_item.region != base.region
            or engineer_item.shift_start.date() != base.planning_date
        ):
            raise PlanningEventTargetMissing
        expected = request.event_type == ReplanningEventType.ENGINEER_AVAILABLE
        if engineer_item.is_available == expected:
            raise PlanningEngineerStateConflict
        return engineer_item.id

    async def _validate_cancel_target(
        self, target: uuid.UUID | None, base: ReplanBaseSnapshot
    ) -> uuid.UUID:
        item = next((item for item in base.requests if item.id == target), None)
        if item is None and target is not None:
            persisted = await self._uow.requests.get_by_id(target)
            if (
                persisted is not None
                and persisted.region == base.region
                and persisted.window_start.date() == base.planning_date
                and persisted.status == RequestStatus.CANCELLED
            ):
                raise PlanningRequestAlreadyCancelled
        if (
            item is None
            or item.region != base.region
            or item.window_start.date() != base.planning_date
        ):
            raise PlanningEventTargetMissing
        if item.status == RequestStatus.CANCELLED:
            raise PlanningRequestAlreadyCancelled
        if item.status in (RequestStatus.IN_PROGRESS, RequestStatus.DONE):
            raise PlanningRequestAlreadyStarted
        return item.id

    async def _to_replan_event(
        self, request: EventPlanningCommand, target_id: uuid.UUID, occurred_at: datetime
    ) -> ReplanEvent:
        match request.event_type:
            case ReplanningEventType.URGENT_REQUEST:
                model = await self._uow.requests.get_by_id(target_id)
                if model is None:
                    raise RuntimeError("Срочная заявка не сохранена")
                return ReplanEvent(
                    event_type=request.event_type,
                    occurred_at=occurred_at,
                    urgent_request=self._to_request_snapshot(model),
                )
            case ReplanningEventType.REQUEST_CANCELLED:
                return ReplanEvent(
                    event_type=request.event_type, occurred_at=occurred_at, request_id=target_id
                )
        return ReplanEvent(
            event_type=request.event_type, occurred_at=occurred_at, engineer_id=target_id
        )

    async def _layer_matrices(
        self,
        points: Sequence[RoutePoint],
        requests: Sequence[LayerMatrixRequest],
    ) -> list[LayerMatrix]:
        travel_matrices = await self._travel_matrix.build(
            [
                MatrixPoint(id=point.id, latitude=point.latitude, longitude=point.longitude)
                for point in points
            ],
            [
                MatrixRequest(
                    vehicle_type=request.vehicle_type,
                    departure_at=request.traffic_reference_at,
                    source_ids=request.source_ids,
                    target_ids=request.target_ids,
                )
                for request in requests
            ],
        )
        return [
            LayerMatrix(request=request, travel_matrix=travel_matrix)
            for request, travel_matrix in zip(requests, travel_matrices, strict=True)
        ]

    @staticmethod
    def _to_replan_snapshot(base: ReplanBaseSnapshot, mode: DistributionMode) -> ReplanSnapshot:
        """Собирает snapshot replan из утверждённого плана и фактов событий дня.

        Срочная заявка поступила в момент своего события, остальные — к cutoff initial.
        Инженер, последним событием которого было возвращение в строй, получает его время.
        """
        availability = {state.engineer_id: state.is_available for state in base.engineer_states}
        urgent_received_at = {
            event.request_id: event.occurred_at
            for event in base.approved_events
            if event.event_type == ReplanningEventType.URGENT_REQUEST
        }
        returned_at: dict[uuid.UUID, datetime | None] = {}
        for event in base.approved_events:
            if event.engineer_id is not None:
                returned_at[event.engineer_id] = (
                    event.occurred_at
                    if event.event_type == ReplanningEventType.ENGINEER_AVAILABLE
                    else None
                )
        return ReplanSnapshot(
            region=base.region,
            planning_date=base.planning_date,
            calculation_cutoff_at=base.calculation_cutoff_at,
            mode=mode,
            requests=tuple(
                RequestSnapshot(
                    id=item.id,
                    latitude=item.latitude,
                    longitude=item.longitude,
                    window_start=item.window_start,
                    window_end=item.window_end,
                    service_minutes=item.norm_minutes_without_travel,
                    priority=item.priority,
                    required_skill=item.required_skill,
                    required_vehicle_type=item.required_vehicle_type,
                    status=item.status,
                    received_at=urgent_received_at.get(item.id, base.initial_cutoff_at),
                )
                for item in base.requests
                if item.latitude is not None and item.longitude is not None
            ),
            engineers=tuple(
                EngineerSnapshot(
                    id=item.id,
                    start_latitude=item.start_point_latitude,
                    start_longitude=item.start_point_longitude,
                    shift_start=item.shift_start,
                    shift_end=item.shift_end,
                    skills=frozenset(item.skills),
                    vehicle_type=item.vehicle_type,
                    is_available=availability[item.id],
                    returned_at=returned_at.get(item.id),
                )
                for item in base.engineers
            ),
            base_stops=tuple(
                BasePlanStop(
                    engineer_id=item.engineer_id,
                    request_id=item.request_id,
                    sequence_number=item.sequence_number,
                    arrival=item.planned_arrival,
                    start=item.planned_start,
                    finish=item.planned_finish,
                    travel_minutes=item.travel_minutes,
                    distance_km=item.distance_km,
                )
                for item in base.stops
            ),
        )

    async def _persist_replan_result(
        self,
        base: ReplanBaseSnapshot,
        calculated: ReplanResult,
        strategy: PlanStrategy,
        *,
        event_id: uuid.UUID | None = None,
        availability: dict[uuid.UUID, bool] | None = None,
    ) -> uuid.UUID:
        unlocated_ids = [
            item.id for item in base.requests if item.latitude is None or item.longitude is None
        ]
        if availability is None:
            availability = {state.engineer_id: state.is_available for state in base.engineer_states}
        plan_id = self._uow.plans.create(
            PlanCreateDTO(
                region=calculated.region,
                planning_date=calculated.planning_date,
                upload_id=base.upload_id,
                kind=PlanKind.EVENT_REPLAN if event_id else PlanKind.REPLAN,
                based_on_plan_id=base.base_plan_id,
                triggered_by_event_id=event_id,
                calculation_cutoff_at=calculated.calculation_cutoff_at,
                mode=calculated.mode,
                strategy=strategy,
                total_mileage_km=calculated.metrics.total_mileage_km,
                engineers_used_count=calculated.metrics.engineers_used_count,
                assigned_requests_count=calculated.metrics.assigned_requests_count,
                unassigned_requests_count=(
                    calculated.metrics.unassigned_requests_count + len(unlocated_ids)
                ),
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await self._uow.flush()
        self._uow.plan_engineer_states.add_many(
            [
                PlanEngineerStateCreateDTO(
                    plan_id=plan_id,
                    engineer_id=engineer.id,
                    is_available=availability[engineer.id],
                )
                for engineer in base.engineers
            ]
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
                    is_locked=stop.is_locked,
                )
                for route in calculated.routes
                for stop in route.stops
            ]
        )
        self._uow.plan_unassigned_requests.add_many(
            [
                PlanUnassignedRequestCreateDTO(
                    plan_id=plan_id,
                    request_id=item.job_id,
                    reason=item.reason,
                )
                for item in calculated.unassigned
            ]
            + [
                PlanUnassignedRequestCreateDTO(
                    plan_id=plan_id, request_id=request_id, reason=UnassignedReason.NO_ROUTE
                )
                for request_id in unlocated_ids
            ]
        )
        return plan_id

    async def prepare_replan_base(
        self, region: Region, cutoff_at: datetime | None = None
    ) -> ReplanBaseSnapshot:
        """Фиксирует current и полный вход округа для расчёта replan."""
        cutoff = cutoff_at or datetime.now(ZoneInfo("Europe/Moscow")).replace(tzinfo=None)
        planning_date = cutoff.date()
        current = await self._uow.plans.get_current(region, planning_date)
        initial_cutoff_at = await self._uow.plans.get_approved_initial_cutoff(region, planning_date)
        if current is None or initial_cutoff_at is None:
            raise PlanningCurrentPlanMissing

        stops = await self._uow.plan_stops.get_by_plan_id(current.id)
        unassigned = await self._uow.plan_unassigned_requests.get_by_plan_id(current.id)
        engineer_states = await self._uow.plan_engineer_states.get_by_plan_id(current.id)
        request_ids = {stop.request_id for stop in stops} | {item.request_id for item in unassigned}
        engineer_ids = {item.engineer_id for item in engineer_states} | {
            stop.engineer_id for stop in stops
        }
        requests = await self._uow.requests.get_by_ids(request_ids)
        engineers = await self._uow.engineers.get_by_ids(engineer_ids)
        events = await self._uow.replanning_events.list_approved_for_region_day(
            region, planning_date
        )

        if (
            len(requests) != len(request_ids)
            or {item.id for item in requests} != request_ids
            or len(engineers) != len(engineer_ids)
            or {item.id for item in engineers} != engineer_ids
            or len(stops) + len(unassigned) != len(request_ids)
            or len(engineer_states) != len(engineer_ids)
            or {item.engineer_id for item in engineer_states} != engineer_ids
        ):
            raise ValueError("Current plan is not a complete snapshot")

        return ReplanBaseSnapshot(
            base_plan_id=current.id,
            upload_id=current.upload_id,
            mode=current.mode,
            strategy=current.strategy,
            region=region,
            planning_date=planning_date,
            calculation_cutoff_at=cutoff,
            initial_cutoff_at=initial_cutoff_at,
            approved_events=tuple(
                ApprovedEventFact(
                    event_type=event.event_type,
                    request_id=event.request_id,
                    engineer_id=event.engineer_id,
                    occurred_at=event.occurred_at.replace(tzinfo=UTC)
                    .astimezone(ZoneInfo("Europe/Moscow"))
                    .replace(tzinfo=None),
                )
                for event in events
            ),
            requests=tuple(
                RequestDTO.from_orm(item)
                for item in sorted(requests, key=lambda item: str(item.id))
            ),
            engineers=tuple(
                EngineerDTO.from_orm(item)
                for item in sorted(engineers, key=lambda item: str(item.id))
            ),
            engineer_states=tuple(
                ReplanEngineerState(engineer_id=item.engineer_id, is_available=item.is_available)
                for item in sorted(engineer_states, key=lambda item: str(item.engineer_id))
            ),
            stops=tuple(
                ReplanStop(
                    engineer_id=item.engineer_id,
                    request_id=item.request_id,
                    sequence_number=item.sequence_number,
                    planned_arrival=item.planned_arrival,
                    planned_start=item.planned_start,
                    planned_finish=item.planned_finish,
                    travel_minutes=item.travel_minutes,
                    distance_km=item.distance_km,
                    is_locked=item.is_locked,
                )
                for item in sorted(
                    stops, key=lambda item: (str(item.engineer_id), item.sequence_number)
                )
            ),
            unassigned=tuple(
                ReplanUnassigned(request_id=item.request_id, reason=item.reason)
                for item in sorted(unassigned, key=lambda item: str(item.request_id))
            ),
        )

    async def import_initial_data(
        self,
        files: list[PlanningUploadFile],
        mode: DistributionMode,
        strategy: PlanStrategy,
    ) -> InitialPlanningResult:
        if not files:
            raise PlanningFileCountError
        identified = await asyncio.gather(
            *(asyncio.to_thread(PlanningWorkbookParser.identify_region, file) for file in files)
        )
        grouped_files: dict[Region, list[PlanningUploadFile]] = {}
        for region, file in zip(identified, files, strict=True):
            grouped_files.setdefault(region, []).append(file)

        regions: list[PlanningRegionResult] = []
        for region in sorted(grouped_files, key=lambda item: item.value):
            try:
                region_files = grouped_files[region]
                if len(region_files) != 2:
                    raise PlanningRegionPairError
                parsed = await asyncio.gather(
                    *(
                        asyncio.to_thread(PlanningWorkbookParser.parse, file)
                        for file in region_files
                    )
                )
                pair = PlanningWorkbookParser.build_region_pairs(parsed)[region]
            except (PlanningFileValidationError, PlanningRegionPairError) as exc:
                code, detail = self._region_error(exc)
                regions.append(
                    PlanningRegionResult(
                        region=region, status="error", error_code=code, error_detail=detail
                    )
                )
                continue
            regions.append(
                await self._run_region(region, pair["requests"], pair["engineers"], mode, strategy)
            )

        successful = sum(item.status == "success" for item in regions)
        status: Literal["success", "partial_success", "error"]
        if successful == len(regions):
            status = "success"
        elif successful:
            status = "partial_success"
        else:
            status = "error"
        return InitialPlanningResult(status=status, regions=tuple(regions))

    async def _run_region(
        self,
        region: Region,
        requests_workbook: ParsedWorkbook,
        engineers_workbook: ParsedWorkbook,
        mode: DistributionMode,
        strategy: PlanStrategy,
    ) -> PlanningRegionResult:
        uploaded_objects: list[tuple[str, str]] = []
        planning_date = min(request.window_start for request in requests_workbook.requests).date()
        try:
            if planning_date != datetime.now(ZoneInfo("Europe/Moscow")).date():
                raise PlanningWrongDateError
            await self._uow.plans.lock_region_day(region, planning_date)
            if await self._uow.plans.has_approved_initial(region, planning_date):
                await self._uow.rollback()
                return PlanningRegionResult(
                    region=region,
                    status="error",
                    error_code="initial_already_approved",
                    error_detail="Первичный план округа за этот день уже утверждён",
                )
            external_ids = [request.external_id for request in requests_workbook.requests]
            if len(external_ids) != len(set(external_ids)):
                raise RepeatedRequestError
            if any(
                request.window_start.date() != planning_date
                for request in requests_workbook.requests
            ):
                raise PlanningFileValidationError
            coordinates = await self._prepare_region(requests_workbook, engineers_workbook)
            upload_id, requests, engineers = await self._persist_region(
                region, requests_workbook, engineers_workbook, coordinates, uploaded_objects
            )
            await self._uow.flush()
            cutoff_at = datetime.now(ZoneInfo("Europe/Moscow")).replace(tzinfo=None)
            plan_id = await self._calculate_and_persist_initial(
                upload_id,
                region,
                planning_date,
                cutoff_at,
                requests,
                engineers,
                mode,
                strategy,
            )
            await self._uow.flush()
            plan = await self._uow.plans.get_by_id(plan_id)
            if plan is None:
                raise RuntimeError("Сохранённый план не найден")
            summary = InitialPlanSummary(
                id=plan.id,
                region=plan.region,
                mode=plan.mode,
                strategy=plan.strategy,
                planning_date=plan.planning_date,
                created_at=plan.created_at,
                approval_deadline=InitialApprovalPolicy.deadline(plan.created_at),
                assigned_requests_count=plan.assigned_requests_count,
                unassigned_requests_count=plan.unassigned_requests_count,
                engineers_used_count=plan.engineers_used_count,
                total_mileage_km=plan.total_mileage_km,
            )
            await self._uow.commit()
            return PlanningRegionResult(region=region, status="success", plan_summary=summary)
        except Exception as exc:
            try:
                await self._uow.rollback()
            finally:
                cleaned = await self._delete_uploaded_objects(uploaded_objects)
            code, detail = self._region_error(exc)
            if code == "internal_error":
                log.exception("planning.initial_region_failed", extra={"region": region.value})
            if not cleaned:
                code = "storage_cleanup_failed"
                detail = "Не удалось очистить файлы неуспешного округа"
            return PlanningRegionResult(
                region=region, status="error", error_code=code, error_detail=detail
            )

    @staticmethod
    def _region_error(exc: Exception) -> tuple[str, str]:
        errors: tuple[tuple[type[Exception], str, str], ...] = (
            (RepeatedRequestError, "duplicate_request", "Повторяются номера заявок"),
            (PlanningFileValidationError, "invalid_file", "Некорректные данные Excel"),
            (
                PlanningWrongDateError,
                "wrong_planning_date",
                "Дата заявок в таблице не совпадает с сегодняшним днём",
            ),
            (PlanningRegionPairError, "invalid_region_pair", "Нужна пара Excel округа"),
            (PlanningAddressNotFound, "address_not_found", "Адрес не найден"),
            (PlanningGeocodingUnavailable, "geocoding_unavailable", "Геокодирование недоступно"),
            (S3UnavailableError, "storage_unavailable", "Хранилище файлов недоступно"),
            (TravelMatrixUnavailableError, "routing_unavailable", "Маршрутизация недоступна"),
            (
                InvalidTravelMatrixResponseError,
                "invalid_routing_response",
                "Некорректный ответ маршрутизации",
            ),
            (MissingCoordinatesError, "missing_coordinates", "Не определены координаты"),
        )
        for error_type, code, detail in errors:
            if isinstance(exc, error_type):
                return code, detail
        return "internal_error", "Не удалось рассчитать план округа"

    async def _calculate_and_persist_initial(
        self,
        upload_id: uuid.UUID,
        region: Region,
        planning_date: date,
        cutoff_at: datetime,
        requests: list[Request],
        engineers: list[EngineerModel],
        mode: DistributionMode,
        strategy: PlanStrategy,
    ) -> uuid.UUID:
        draft = self._algorithm.prepare_initial(
            InitialPlanningSnapshot(
                region=region,
                planning_date=planning_date,
                calculation_cutoff_at=cutoff_at,
                mode=mode,
                requests=tuple(
                    self._to_request_snapshot(request)
                    for request in requests
                    if request.latitude is not None and request.longitude is not None
                ),
                engineers=tuple(self._to_engineer_snapshot(engineer) for engineer in engineers),
            )
        )
        matrices = await self._layer_matrices(draft.points, draft.matrix_requests)
        planning_input = self._algorithm.build_initial_input(draft, matrices)
        calculated = self._algorithm.plan_initial(planning_input, AlgorithmVariant(strategy.value))
        baseline = self._algorithm.plan_baseline(planning_input)
        unlocated_ids = [
            request.id
            for request in requests
            if request.latitude is None or request.longitude is None
        ]
        plan_id = await self._persist_initial_result(
            upload_id, calculated, strategy, engineers, unlocated_ids
        )
        self._uow.baseline_results.create(
            BaselineResultCreateDTO(
                initial_plan_id=plan_id,
                assigned_requests_count=baseline.metrics.assigned_requests_count,
                unassigned_requests_count=baseline.metrics.unassigned_requests_count,
                engineers_used_count=baseline.metrics.engineers_used_count,
                total_mileage_km=baseline.metrics.total_mileage_km,
                average_workload_with_travel=(
                    baseline.metrics.average_utilization_with_travel * Decimal("100")
                ).quantize(Decimal("0.01")),
                average_workload_without_travel=(
                    baseline.metrics.average_utilization_without_travel * Decimal("100")
                ).quantize(Decimal("0.01")),
                algorithm_version=baseline.algorithm_version,
            )
        )
        return plan_id

    async def _persist_initial_result(
        self,
        upload_id: uuid.UUID,
        calculated: AlgorithmInitialPlanningResult,
        strategy: PlanStrategy,
        engineers: list[EngineerModel],
        unlocated_ids: list[uuid.UUID],
    ) -> uuid.UUID:
        """Сохраняет initial; заявки без координат — неназначенные с причиной `no_route`."""
        plan_id = self._uow.plans.create(
            PlanCreateDTO(
                region=calculated.region,
                planning_date=calculated.planning_date,
                upload_id=upload_id,
                kind=PlanKind.INITIAL,
                based_on_plan_id=None,
                triggered_by_event_id=None,
                calculation_cutoff_at=calculated.calculation_cutoff_at,
                mode=calculated.mode,
                strategy=strategy,
                total_mileage_km=calculated.metrics.total_mileage_km,
                engineers_used_count=calculated.metrics.engineers_used_count,
                assigned_requests_count=calculated.metrics.assigned_requests_count,
                unassigned_requests_count=(
                    calculated.metrics.unassigned_requests_count + len(unlocated_ids)
                ),
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        # UUID-связи без ORM relationships не задают порядок INSERT при flush.
        await self._uow.flush()
        self._uow.plan_engineer_states.add_many(
            [
                PlanEngineerStateCreateDTO(
                    plan_id=plan_id,
                    engineer_id=engineer.id,
                    is_available=engineer.is_available,
                )
                for engineer in engineers
            ]
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
                for route in calculated.routes
                for stop in route.stops
            ]
        )
        self._uow.plan_unassigned_requests.add_many(
            [
                PlanUnassignedRequestCreateDTO(
                    plan_id=plan_id,
                    request_id=item.job_id,
                    reason=item.reason,
                )
                for item in calculated.unassigned
            ]
            + [
                PlanUnassignedRequestCreateDTO(
                    plan_id=plan_id, request_id=request_id, reason=UnassignedReason.NO_ROUTE
                )
                for request_id in unlocated_ids
            ]
        )
        return plan_id

    @staticmethod
    def _to_request_snapshot(request: Request) -> RequestSnapshot:
        return RequestSnapshot(
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
    def _to_engineer_snapshot(engineer: EngineerModel) -> EngineerSnapshot:
        return EngineerSnapshot(
            id=engineer.id,
            start_latitude=engineer.start_point_latitude,
            start_longitude=engineer.start_point_longitude,
            shift_start=engineer.shift_start,
            shift_end=engineer.shift_end,
            skills=frozenset(skill.skill for skill in engineer.skills),
            vehicle_type=engineer.vehicle_type,
            is_available=engineer.is_available,
        )

    async def _prepare_region(
        self,
        requests_workbook: ParsedWorkbook,
        engineers_workbook: ParsedWorkbook,
    ) -> dict[str, Coordinates]:
        if requests_workbook.office_address is None:
            raise PlanningFileValidationError
        addresses = [requests_workbook.office_address]
        addresses.extend(request.address for request in requests_workbook.requests)
        addresses.extend(engineer.start_point_address for engineer in engineers_workbook.engineers)
        unique_addresses = list(dict.fromkeys(addresses))
        points = await asyncio.gather(
            *(self._geocoding.geocode(address) for address in unique_addresses),
            return_exceptions=True,
        )
        coordinates = {}
        for address, point in zip(unique_addresses, points, strict=True):
            if isinstance(point, GeocodingUnavailableError):
                raise PlanningGeocodingUnavailable from point
            if isinstance(point, AddressNotFoundError):
                # Без офиса округ не спланировать; остальные ненайденные адреса не роняют
                # округ: заявка уйдёт в неназначенные, бригада стартует из офиса.
                if address == requests_workbook.office_address:
                    raise PlanningAddressNotFound from point
                continue
            if isinstance(point, BaseException):
                raise point
            coordinates[address] = point
        return coordinates

    async def _persist_region(
        self,
        region: Region,
        requests_workbook: ParsedWorkbook,
        engineers_workbook: ParsedWorkbook,
        coordinates: dict[str, Coordinates],
        uploaded_objects: list[tuple[str, str]],
    ) -> tuple[uuid.UUID, list[Request], list[EngineerModel]]:
        upload_id = self._uow.data_uploads.create(region)
        file_dtos: list[UploadedFileCreateDTO] = []
        for workbook in (requests_workbook, engineers_workbook):
            bucket = cfg.s3.bucket_uploads
            safe_filename = Path(workbook.source.filename).name
            key = f"planning/{upload_id}/{uuid.uuid7()}-{safe_filename}"
            uploaded_objects.append((bucket, key))
            await self._storage.upload_file(
                bucket,
                key,
                workbook.source.data,
                workbook.source.content_type,
            )
            file_dtos.append(
                UploadedFileCreateDTO(
                    upload_id=upload_id,
                    filename=safe_filename,
                    content_type=workbook.source.content_type,
                    size_bytes=len(workbook.source.data),
                    s3_bucket=bucket,
                    s3_key=key,
                )
            )

        if requests_workbook.office_address is None:
            raise PlanningFileValidationError
        planning_date = min(request.window_start for request in requests_workbook.requests).date()
        office = coordinates[requests_workbook.office_address]
        engineer_starts = {
            engineer.start_point_address: coordinates.get(engineer.start_point_address, office)
            for engineer in engineers_workbook.engineers
        }

        request_dtos = [
            RequestCreateDTO(
                upload_id=upload_id,
                external_id=request.external_id,
                type_bk=request.type_bk,
                type_hd=request.type_hd,
                region=region,
                district=request.district,
                address=request.address,
                latitude=(
                    coordinates[request.address].latitude
                    if request.address in coordinates
                    else None
                ),
                longitude=(
                    coordinates[request.address].longitude
                    if request.address in coordinates
                    else None
                ),
                connection_type=request.connection_type,
                is_gigabit=request.is_gigabit,
                window_start=request.window_start,
                window_end=request.window_end,
                norm_minutes=request.norm_minutes,
                norm_minutes_without_travel=request.norm_minutes_without_travel,
                priority=request.priority,
                required_skill=request.required_skill,
                required_vehicle_type=None,
            )
            for request in requests_workbook.requests
        ]
        engineer_dtos = [
            EngineerCreateDTO(
                upload_id=upload_id,
                name=engineer.name,
                region=region,
                start_point_address=engineer.start_point_address,
                start_point_latitude=engineer_starts[engineer.start_point_address].latitude,
                start_point_longitude=engineer_starts[engineer.start_point_address].longitude,
                shift_start=datetime.combine(planning_date, engineer.shift_start),
                shift_end=datetime.combine(planning_date, engineer.shift_end),
                skills=engineer.skills,
                vehicle_type=engineer.vehicle_type,
            )
            for engineer in engineers_workbook.engineers
        ]
        self._uow.uploaded_files.add_many(file_dtos)
        requests = self._uow.requests.add_many(request_dtos)
        engineers = self._uow.engineers.add_many(engineer_dtos)
        return upload_id, requests, engineers

    async def _delete_uploaded_objects(self, objects: list[tuple[str, str]]) -> bool:
        cleaned = True
        for bucket, key in objects:
            for attempt in range(3):
                try:
                    await self._storage.delete_file(bucket, key)
                    break
                except S3UnavailableError as exc:
                    if attempt < 2:
                        await asyncio.sleep(0.1 * (attempt + 1))
                        continue
                    cleaned = False
                    log.error(
                        "planning.s3_cleanup_failed",
                        exc_info=exc,
                        extra={"s3": {"bucket": bucket, "upload_id": key.split("/", 2)[1]}},
                    )
        return cleaned
