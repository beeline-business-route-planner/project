from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, UploadFile

from src.api.exc.planning import (
    InvalidPlanningFile,
    InvalidPlanningFileCount,
    InvalidPlanningRegionPair,
    PlanningAddressNotFound,
    PlanningGeocodingUnavailable,
    PlanningInvalidRoutingResponse,
    PlanningMissingCoordinates,
    PlanningRoutingUnavailable,
    PlanningUnreachablePoints,
    RepeatedPlanningRequest,
)
from src.api.planning.schemas import InitialPlanningResponse, PlanningImportResponse
from src.config import cfg
from src.core.geocoding import AddressNotFoundError, GeocodingUnavailableError
from src.core.routing import (
    InvalidRoutingResponseError,
    RoutingUnavailableError,
    UnreachablePointsError,
)
from src.core.services import (
    MissingCoordinatesError,
    PlanningFileCountError,
    PlanningFileValidationError,
    PlanningRegionPairError,
    PlanningService,
    PlanningUploadFile,
    RepeatedRequestError,
)

router = APIRouter(prefix="/planning", tags=["planning"], route_class=DishkaRoute)


@router.post("/initial", response_model=InitialPlanningResponse)
async def import_initial_planning_data(
    service: FromDishka[PlanningService],
    files: Annotated[list[UploadFile], File()],
) -> InitialPlanningResponse:
    uploaded_files: list[PlanningUploadFile] = []
    try:
        for file in files:
            uploaded_files.append(
                PlanningUploadFile(
                    filename=file.filename or "",
                    content_type=(
                        file.content_type
                        or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                    data=await file.read(cfg.planning.max_file_size_bytes + 1),
                )
            )
    finally:
        for file in files:
            await file.close()

    try:
        result = await service.import_initial_data(uploaded_files)
    except PlanningFileCountError as exc:
        raise InvalidPlanningFileCount from exc
    except PlanningRegionPairError as exc:
        raise InvalidPlanningRegionPair from exc
    except PlanningFileValidationError as exc:
        raise InvalidPlanningFile from exc
    except RepeatedRequestError as exc:
        raise RepeatedPlanningRequest from exc
    except AddressNotFoundError as exc:
        raise PlanningAddressNotFound from exc
    except GeocodingUnavailableError as exc:
        raise PlanningGeocodingUnavailable from exc
    except RoutingUnavailableError as exc:
        raise PlanningRoutingUnavailable from exc
    except InvalidRoutingResponseError as exc:
        raise PlanningInvalidRoutingResponse from exc
    except UnreachablePointsError as exc:
        raise PlanningUnreachablePoints from exc
    except MissingCoordinatesError as exc:
        raise PlanningMissingCoordinates from exc

    return InitialPlanningResponse(
        status=result.status,
        imports=[
            PlanningImportResponse(
                upload_id=item.upload_id,
                region=item.region,
                requests_count=item.requests_count,
                engineers_count=item.engineers_count,
                plan_id=item.plan_id,
            )
            for item in result.imports
        ],
    )
