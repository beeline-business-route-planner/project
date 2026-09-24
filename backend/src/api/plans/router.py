import uuid
from datetime import date

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from src.api.plans.schemas import PlanDetailResponse, PlanSummaryResponse
from src.api.plans.service import PlanService
from src.core.db.enums import Region

router = APIRouter(prefix="/plans", tags=["plans"], route_class=DishkaRoute)

# "/current" обязан быть объявлен раньше "/{plan_id}" — иначе Starlette
# по порядку регистрации маршрутов примет "current" за uuid path-параметра.


@router.get("/current", response_model=PlanDetailResponse)
async def get_current_plan(
    service: FromDishka[PlanService], region: Region, planning_date: date | None = None
) -> PlanDetailResponse:
    plan = await service.get_current(region, planning_date)
    return PlanDetailResponse.model_validate(plan)


@router.get("", response_model=list[PlanSummaryResponse])
async def list_plans(service: FromDishka[PlanService], region: Region) -> list[PlanSummaryResponse]:
    plans = await service.list_by_region(region)
    return [PlanSummaryResponse.model_validate(item) for item in plans]


@router.get("/{plan_id}", response_model=PlanDetailResponse)
async def get_plan(service: FromDishka[PlanService], plan_id: uuid.UUID) -> PlanDetailResponse:
    plan = await service.get_by_id(plan_id)
    return PlanDetailResponse.model_validate(plan)
