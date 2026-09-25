from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, UploadFile

from src.api.planning.dto import PlanningUploadFile
from src.api.planning.schemas import (
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
