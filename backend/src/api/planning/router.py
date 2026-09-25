from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, UploadFile

from src.api.planning.dto import PlanningUploadFile
from src.api.planning.schemas import (
    EventPlanningRequest,
    EventPlanningResponse,
    InitialPlanningResponse,
    InitialPlanSummaryResponse,
    PlanningRegionErrorResponse,
    PlanningRegionResponse,
    ReplanPlanningRequest,
    ReplanPlanningResponse,
    ReplanPlanSummaryResponse,
    ReplanRegionResponse,
)
from src.api.planning.service import PlanningService
from src.config import cfg
from src.core.db.enums import PlanKind

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

    result = await service.import_initial_data(uploaded_files)
    return InitialPlanningResponse(
        status=result.status,
        regions=[
            PlanningRegionResponse(
                region=item.region,
                status=item.status,
                plan_summary=(
                    InitialPlanSummaryResponse.model_validate(
                        item.plan_summary, from_attributes=True
                    )
                    if item.plan_summary is not None
                    else None
                ),
                error=(
                    PlanningRegionErrorResponse(code=item.error_code, detail=item.error_detail)
                    if item.error_code is not None and item.error_detail is not None
                    else None
                ),
            )
            for item in result.regions
        ],
    )


@router.post("/replan", response_model=ReplanPlanningResponse)
async def replan(
    request: ReplanPlanningRequest,
    service: FromDishka[PlanningService],
) -> ReplanPlanningResponse:
    result = await service.replan(request.regions)
    return ReplanPlanningResponse(
        status=result.status,
        regions=[
            ReplanRegionResponse(
                region=item.region,
                status=item.status,
                plan_summary=(
                    ReplanPlanSummaryResponse.model_validate(
                        item.plan_summary, from_attributes=True
                    )
                    if item.plan_summary is not None
                    else None
                ),
                error=(
                    PlanningRegionErrorResponse(code=item.error_code, detail=item.error_detail)
                    if item.error_code is not None and item.error_detail is not None
                    else None
                ),
            )
            for item in result.regions
        ],
    )


@router.post("/events", response_model=EventPlanningResponse, status_code=201)
async def create_event(
    request: EventPlanningRequest,
    service: FromDishka[PlanningService],
) -> EventPlanningResponse:
    result = await service.create_event(request)
    return EventPlanningResponse(
        event_id=result.event_id,
        event_type=result.event_type,
        request_id=result.request_id,
        engineer_id=result.engineer_id,
        occurred_at=result.occurred_at,
        plan=ReplanPlanSummaryResponse.model_validate(result.plan, from_attributes=True).model_copy(
            update={"kind": PlanKind.EVENT_REPLAN}
        ),
    )
