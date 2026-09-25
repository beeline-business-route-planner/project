import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from src.api.exc.planning import (
    PlanningAddressNotFound,
    PlanningFileCountError,
    PlanningFileValidationError,
    PlanningGeocodingUnavailable,
    PlanningRegionPairError,
    RepeatedRequestError,
)
from src.api.planning.dto import (
    InitialPlanningResult,
    InitialPlanSummary,
    ParsedWorkbook,
    PlanningRegionResult,
    PlanningUploadFile,
)
from src.api.planning.parser import PlanningWorkbookParser
from src.config import cfg
from src.core.algorithm import (
    AlgorithmService,
    DistributionMode,
    EngineerSnapshot,
    InitialPlanningSnapshot,
    LayerMatrix,
    MissingCoordinatesError,
    RequestSnapshot,
)
from src.core.algorithm import (
    InitialPlanningResult as AlgorithmInitialPlanningResult,
)
from src.core.db.dto import (
    BaselineResultCreateDTO,
    EngineerCreateDTO,
    PlanCreateDTO,
    PlanEngineerStateCreateDTO,
    PlanStopCreateDTO,
    PlanUnassignedRequestCreateDTO,
    RequestCreateDTO,
    UploadedFileCreateDTO,
)
from src.core.db.enums import PlanKind, Region
from src.core.db.models import Engineer as EngineerModel
from src.core.db.models import Request
from src.core.db.uow import UnitOfWork
from src.core.dgis import (
    DgisMatrixService,
    DgisPoint,
    DgisUnavailableError,
    DgisUnreachablePointsError,
    InvalidDgisResponseError,
)
from src.core.geocoding import (
    AddressNotFoundError,
    Coordinates,
    GeocodingService,
    GeocodingUnavailableError,
)
from src.core.s3 import S3Storage, S3UnavailableError

log = logging.getLogger(__name__)


class PlanningService:
    """Создаёт независимые initial-кандидаты для округов из Excel-пар."""

    def __init__(
        self,
        uow: UnitOfWork,
        geocoding: GeocodingService,
        storage: S3Storage,
        algorithm: AlgorithmService,
        dgis: DgisMatrixService,
    ) -> None:
        self._uow = uow
        self._geocoding = geocoding
        self._storage = storage
        self._algorithm = algorithm
        self._dgis = dgis

    async def import_initial_data(self, files: list[PlanningUploadFile]) -> InitialPlanningResult:
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
            regions.append(await self._run_region(region, pair["requests"], pair["engineers"]))

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
    ) -> PlanningRegionResult:
        uploaded_objects: list[tuple[str, str]] = []
        planning_date = min(request.window_start for request in requests_workbook.requests).date()
        try:
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
                DistributionMode.MIN_ENGINEERS,
            )
            await self._uow.flush()
            plan = await self._uow.plans.get_by_id(plan_id)
            if plan is None:
                raise RuntimeError("Сохранённый план не найден")
            summary = InitialPlanSummary(
                id=plan.id,
                region=plan.region,
                planning_date=plan.planning_date,
                created_at=plan.created_at,
                approval_deadline=plan.created_at
                + timedelta(minutes=cfg.planning.approval_ttl_minutes),
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
            (PlanningRegionPairError, "invalid_region_pair", "Нужна пара Excel округа"),
            (PlanningAddressNotFound, "address_not_found", "Адрес не найден"),
            (PlanningGeocodingUnavailable, "geocoding_unavailable", "Геокодирование недоступно"),
            (S3UnavailableError, "storage_unavailable", "Хранилище файлов недоступно"),
            (DgisUnavailableError, "routing_unavailable", "Маршрутизация недоступна"),
            (
                InvalidDgisResponseError,
                "invalid_routing_response",
                "Некорректный ответ маршрутизации",
            ),
            (DgisUnreachablePointsError, "unreachable_points", "Маршрут между точками не найден"),
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
    ) -> uuid.UUID:
        draft = self._algorithm.prepare_initial(
            InitialPlanningSnapshot(
                region=region,
                planning_date=planning_date,
                calculation_cutoff_at=cutoff_at,
                mode=mode,
                requests=tuple(self._to_request_snapshot(request) for request in requests),
                engineers=tuple(self._to_engineer_snapshot(engineer) for engineer in engineers),
            )
        )
        points = [
            DgisPoint(id=point.id, latitude=point.latitude, longitude=point.longitude)
            for point in draft.points
        ]
        matrices = [
            LayerMatrix(
                request=matrix_request,
                travel_matrix=await self._dgis.build_matrix(
                    points,
                    vehicle_type=matrix_request.vehicle_type,
                    departure_at=matrix_request.traffic_reference_at,
                    source_ids=matrix_request.source_ids,
                    target_ids=matrix_request.target_ids,
                ),
            )
            for matrix_request in draft.matrix_requests
        ]
        planning_input = self._algorithm.build_initial_input(draft, matrices)
        calculated = self._algorithm.plan_initial(planning_input)
        baseline = self._algorithm.plan_baseline(planning_input)
        plan_id = self._persist_initial_result(upload_id, calculated, engineers)
        self._uow.baseline_results.create(
            BaselineResultCreateDTO(
                initial_plan_id=plan_id,
                assigned_requests_count=baseline.metrics.assigned_requests_count,
                unassigned_requests_count=baseline.metrics.unassigned_requests_count,
                engineers_used_count=baseline.metrics.engineers_used_count,
                total_mileage_km=baseline.metrics.total_mileage_km,
                average_workload_with_travel=baseline.metrics.average_utilization_with_travel,
                average_workload_without_travel=(
                    baseline.metrics.average_utilization_without_travel
                ),
                algorithm_version=baseline.algorithm_version,
            )
        )
        return plan_id

    def _persist_initial_result(
        self,
        upload_id: uuid.UUID,
        calculated: AlgorithmInitialPlanningResult,
        engineers: list[EngineerModel],
    ) -> uuid.UUID:
        plan_id = self._uow.plans.create(
            PlanCreateDTO(
                region=calculated.region,
                planning_date=calculated.planning_date,
                upload_id=upload_id,
                kind=PlanKind.INITIAL,
                based_on_plan_id=None,
                triggered_by_event_id=None,
                calculation_cutoff_at=calculated.calculation_cutoff_at,
                total_mileage_km=calculated.metrics.total_mileage_km,
                engineers_used_count=calculated.metrics.engineers_used_count,
                assigned_requests_count=calculated.metrics.assigned_requests_count,
                unassigned_requests_count=calculated.metrics.unassigned_requests_count,
                created_at=datetime.now(ZoneInfo("Europe/Moscow")).replace(tzinfo=None),
            )
        )
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
        coordinates = {}
        for address in dict.fromkeys(addresses):
            try:
                point = await self._geocoding.geocode(address)
            except AddressNotFoundError as exc:
                raise PlanningAddressNotFound from exc
            except GeocodingUnavailableError as exc:
                raise PlanningGeocodingUnavailable from exc
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

        request_dtos = [
            RequestCreateDTO(
                upload_id=upload_id,
                external_id=request.external_id,
                type_bk=request.type_bk,
                type_hd=request.type_hd,
                region=region,
                district=request.district,
                address=request.address,
                latitude=coordinates[request.address].latitude,
                longitude=coordinates[request.address].longitude,
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
                start_point_latitude=coordinates[engineer.start_point_address].latitude,
                start_point_longitude=coordinates[engineer.start_point_address].longitude,
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
