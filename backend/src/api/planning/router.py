from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, UploadFile

from src.api.planning.dto import PlanningUploadFile
from src.api.planning.schemas import InitialPlanningResponse, PlanningImportResponse
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
