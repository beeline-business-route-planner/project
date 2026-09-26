from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, UploadFile

from src.api.planning.dto import (
    EventPlanningCommand,
    PlanningUploadFile,
    UrgentRequestData,
)
from src.api.planning.schemas import (
    EventPlanningRequest,
    EventPlanningResponse,
    EventPlanSummaryResponse,
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
    payload = request.urgent_request
    urgent = (
        UrgentRequestData(
            external_id=payload.external_id,
            type_bk=payload.type_bk,
            type_hd=payload.type_hd,
            district=payload.district,
            address=payload.address,
            connection_type=payload.connection_type,
            is_gigabit=payload.is_gigabit,
            window_start=payload.window_start,
            window_end=payload.window_end,
            norm_minutes=payload.norm_minutes,
            norm_minutes_without_travel=payload.norm_minutes_without_travel,
            priority=payload.priority,
            required_skill=payload.required_skill,
            required_vehicle_type=payload.required_vehicle_type,
        )
        if payload is not None
        else None
    )
    result = await service.create_event(
        EventPlanningCommand(
            region=request.region,
            event_type=request.event_type,
            request_id=request.request_id,
            engineer_id=request.engineer_id,
            urgent_request=urgent,
        )
    )
    return EventPlanningResponse(
        event_id=result.event_id,
        event_type=result.event_type,
        request_id=result.request_id,
        engineer_id=result.engineer_id,
        occurred_at=result.occurred_at,
        plan=EventPlanSummaryResponse.model_validate(result.plan, from_attributes=True),
    )
