from datetime import date

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from src.api.reports.schemas import DailyReportExportResponse
from src.api.reports.service import DailyReportExportService

router = APIRouter(prefix="/reports", tags=["reports"], route_class=DishkaRoute)


@router.get("/daily", response_model=DailyReportExportResponse)
async def export_daily_report(
    service: FromDishka[DailyReportExportService], planning_date: date
) -> DailyReportExportResponse:
    result = await service.export(planning_date)
    return DailyReportExportResponse.model_validate(result, from_attributes=True)
