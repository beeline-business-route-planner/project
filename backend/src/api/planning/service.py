import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path

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
from src.core.algorithm import AlgorithmService, DistributionMode, MissingCoordinatesError
from src.core.db.dto import EngineerCreateDTO, RequestCreateDTO, UploadedFileCreateDTO
from src.core.db.enums import Region, VehicleType
from src.core.db.uow import UnitOfWork
from src.core.geocoding import (
    AddressNotFoundError,
    Coordinates,
    GeocodingService,
    GeocodingUnavailableError,
)
from src.core.routing import (
    InvalidRoutingResponseError,
    RoutingUnavailableError,
    UnreachablePointsError,
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
    ) -> None:
        self._uow = uow
        self._geocoding = geocoding
        self._storage = storage
        self._algorithm = algorithm

    async def import_initial_data(self, files: list[PlanningUploadFile]) -> InitialPlanningResult:
        if not files or len(files) % 2 != 0:
            raise PlanningFileCountError

        parsed_workbooks = await asyncio.gather(
            *(asyncio.to_thread(PlanningWorkbookParser.parse, file) for file in files)
        )
        region_pairs = PlanningWorkbookParser.build_region_pairs(parsed_workbooks)
        all_external_ids = [
            request.external_id
            for pair in region_pairs.values()
            for request in pair["requests"].requests
        ]
        if len(all_external_ids) != len(set(all_external_ids)):
            raise RepeatedRequestError

        existing_ids = await self._uow.requests.get_existing_external_ids(set(all_external_ids))
        if existing_ids:
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
            plans = [
                await self._algorithm.plan_initial(
                    result.upload_id, result.region, DistributionMode.MIN_ENGINEERS
                )
                for result in results
            ]
        except RoutingUnavailableError as exc:
            raise PlanningRoutingUnavailable from exc
        except InvalidRoutingResponseError as exc:
            raise PlanningInvalidRoutingResponse from exc
        except UnreachablePointsError as exc:
            raise PlanningUnreachablePoints from exc
        except MissingCoordinatesError as exc:
            raise PlanningMissingCoordinates from exc
        results_with_plans = [
            replace(result, plan_id=plan.plan_id)
            for result, plan in zip(results, plans, strict=True)
        ]
        return InitialPlanningResult(status="imported", imports=tuple(results_with_plans))

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

        office_address = requests_workbook.office_address
        if office_address is None:
            raise PlanningFileValidationError
        office_coordinates = coordinates[office_address]
        planning_date = min(request.window_start for request in requests_workbook.requests).date()
        vehicle_type = VehicleType(cfg.planning.default_vehicle_type)

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
                start_point_address=office_address,
                start_point_latitude=office_coordinates.latitude,
                start_point_longitude=office_coordinates.longitude,
                shift_start=datetime.combine(planning_date, cfg.planning.default_shift_start),
                shift_end=datetime.combine(planning_date, cfg.planning.default_shift_end),
                skills=engineer.skills,
                vehicle_type=vehicle_type,
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
