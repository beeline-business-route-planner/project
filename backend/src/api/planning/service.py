import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.api.exc.planning import (
    PlanningAddressNotFound,
    PlanningFileCountError,
    PlanningFileValidationError,
    PlanningGeocodingUnavailable,
    PlanningInvalidRoutingResponse,
    PlanningMissingCoordinates,
    PlanningRoutingUnavailable,
    PlanningStorageUnavailable,
    PlanningUnreachablePoints,
    RepeatedRequestError,
)
from src.api.planning.dto import (
    InitialPlanningResult,
    ParsedWorkbook,
    PlanningImportResult,
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
    """Импортирует исходные таблицы для первичного планирования."""

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
        if not files or len(files) % 2 != 0:
            raise PlanningFileCountError

        parsed_workbooks = await asyncio.gather(
            *(asyncio.to_thread(PlanningWorkbookParser.parse, file) for file in files)
        )
        region_pairs = PlanningWorkbookParser.build_region_pairs(parsed_workbooks)
        for pair in region_pairs.values():
            external_ids = [request.external_id for request in pair["requests"].requests]
            if len(external_ids) != len(set(external_ids)):
                raise RepeatedRequestError

        prepared_regions = []
        for region in sorted(region_pairs, key=lambda item: item.value):
            requests_workbook = region_pairs[region]["requests"]
            engineers_workbook = region_pairs[region]["engineers"]
            prepared_regions.append(
                await self._prepare_region(region, requests_workbook, engineers_workbook)
            )

        uploaded_objects: list[tuple[str, str]] = []
        results: list[PlanningImportResult] = []
        try:
            for prepared in prepared_regions:
                results.append(await self._persist_region(*prepared, uploaded_objects))
            await self._uow.commit()
        except S3UnavailableError as exc:
            await self._uow.rollback()
            await self._delete_uploaded_objects(uploaded_objects)
            raise PlanningStorageUnavailable from exc
        except Exception:
            await self._uow.rollback()
            await self._delete_uploaded_objects(uploaded_objects)
            raise

        try:
            plan_ids = [
                await self._calculate_and_persist_initial(
                    result.upload_id,
                    result.region,
                    DistributionMode.MIN_ENGINEERS,
                )
                for result in results
            ]
        except DgisUnavailableError as exc:
            raise PlanningRoutingUnavailable from exc
        except InvalidDgisResponseError as exc:
            raise PlanningInvalidRoutingResponse from exc
        except DgisUnreachablePointsError as exc:
            raise PlanningUnreachablePoints from exc
        except MissingCoordinatesError as exc:
            raise PlanningMissingCoordinates from exc
        results_with_plans = [
            replace(result, plan_id=plan_id)
            for result, plan_id in zip(results, plan_ids, strict=True)
        ]
        return InitialPlanningResult(status="imported", imports=tuple(results_with_plans))

    async def _calculate_and_persist_initial(
        self,
        upload_id: uuid.UUID,
        region: Region,
        mode: DistributionMode,
    ) -> uuid.UUID:
        requests = await self._uow.requests.get_by_upload_id(upload_id)
        engineers = await self._uow.engineers.get_by_upload_id(upload_id)
        if not requests:
            raise PlanningFileValidationError
        requests.sort(key=lambda request: request.id.int)
        engineers.sort(key=lambda engineer: engineer.id.int)

        draft = self._algorithm.prepare_initial(
            InitialPlanningSnapshot(
                region=region,
                planning_date=min(request.window_start for request in requests).date(),
                calculation_cutoff_at=datetime.now(ZoneInfo("Europe/Moscow")).replace(tzinfo=None),
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
        await self._uow.commit()
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
        region: Region,
        requests_workbook: ParsedWorkbook,
        engineers_workbook: ParsedWorkbook,
    ) -> tuple[
        Region,
        ParsedWorkbook,
        ParsedWorkbook,
        dict[str, Coordinates],
    ]:
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
        return region, requests_workbook, engineers_workbook, coordinates

    async def _persist_region(
        self,
        region: Region,
        requests_workbook: ParsedWorkbook,
        engineers_workbook: ParsedWorkbook,
        coordinates: dict[str, Coordinates],
        uploaded_objects: list[tuple[str, str]],
    ) -> PlanningImportResult:
        upload_id = self._uow.data_uploads.create(region)
        file_dtos: list[UploadedFileCreateDTO] = []
        for workbook in (requests_workbook, engineers_workbook):
            bucket = cfg.s3.bucket_uploads
            safe_filename = Path(workbook.source.filename).name
            key = f"planning/{upload_id}/{uuid.uuid7()}-{safe_filename}"
            await self._storage.upload_file(
                bucket,
                key,
                workbook.source.data,
                workbook.source.content_type,
            )
            uploaded_objects.append((bucket, key))
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
        self._uow.requests.add_many(request_dtos)
        self._uow.engineers.add_many(engineer_dtos)
        return PlanningImportResult(
            upload_id=upload_id,
            region=region,
            requests_count=len(request_dtos),
            engineers_count=len(engineer_dtos),
        )

    async def _delete_uploaded_objects(self, objects: list[tuple[str, str]]) -> None:
        for bucket, key in objects:
            try:
                await self._storage.delete_file(bucket, key)
            except S3UnavailableError as exc:
                log.error(
                    "planning.s3_cleanup_failed",
                    exc_info=exc,
                    extra={"s3": {"bucket": bucket, "key": key}},
                )
