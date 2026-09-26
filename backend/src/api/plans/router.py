import uuid
from datetime import date

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from src.api.plans.schemas import (
    EngineerRouteResponse,
    PlanDetailResponse,
    PlanExportResponse,
    PlanSummaryResponse,
)
from src.api.plans.service import PlanExportService, PlanRouteService, PlanService
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


@router.get("/{plan_id}/engineers/{engineer_id}/route", response_model=EngineerRouteResponse)
async def get_engineer_route(
    service: FromDishka[PlanRouteService], plan_id: uuid.UUID, engineer_id: uuid.UUID
) -> EngineerRouteResponse:
    route = await service.get_engineer_route(plan_id, engineer_id)
    return EngineerRouteResponse.model_validate(
        {
            **route.__dict__,
            "geometry": (
                {"type": "LineString", "coordinates": route.geometry}
                if route.geometry is not None
                else None
            ),
        }
    )


@router.get("/{plan_id}/export", response_model=PlanExportResponse)
async def export_plan(
    service: FromDishka[PlanExportService], plan_id: uuid.UUID
) -> PlanExportResponse:
    result = await service.export(plan_id)
    return PlanExportResponse.model_validate(result, from_attributes=True)


@router.post("/{plan_id}/approve", response_model=PlanSummaryResponse)
async def approve_plan(service: FromDishka[PlanService], plan_id: uuid.UUID) -> PlanSummaryResponse:
    plan = await service.approve(plan_id)
    return PlanSummaryResponse.model_validate(plan)


@router.post("/{plan_id}/reject", response_model=PlanSummaryResponse)
async def reject_plan(service: FromDishka[PlanService], plan_id: uuid.UUID) -> PlanSummaryResponse:
    plan = await service.reject(plan_id)
    return PlanSummaryResponse.model_validate(plan)
