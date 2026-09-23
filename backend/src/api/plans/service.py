import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.api.exc.plans import PlanNotFoundError
from src.api.plans.dto import (
    PlanDetailDTO,
    PlanSummaryDTO,
)
from src.api.plans.presenter import PlanPresenter
from src.config import cfg
from src.core.db.enums import Region
from src.core.db.models import Plan
from src.core.db.uow import UnitOfWork


class PlanService:
    """Читает построенный план округа для главного экрана и экрана планирования.

    См. `docs/PLANS_API.md` — юзеркейс, группировка заявок в боксы,
    сортировка. Ничего не пишет — вся запись плана остаётся за
    `AlgorithmService`/`PlanningService`.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def get_current(self, region: Region) -> PlanDetailDTO:
        planning_date = datetime.now(ZoneInfo("Europe/Moscow")).date()
        plan = await self._uow.plans.get_current(region, planning_date)
        if plan is None:
            raise PlanNotFoundError
        return await self._build_detail(plan)

    async def get_by_id(self, plan_id: uuid.UUID) -> PlanDetailDTO:
        plan = await self._uow.plans.get_by_id(plan_id)
        if plan is None:
            raise PlanNotFoundError
        return await self._build_detail(plan)

    async def list_by_region(self, region: Region) -> tuple[PlanSummaryDTO, ...]:
        plans = await self._uow.plans.list_by_region(region)
        return tuple(
            PlanSummaryDTO(
                id=plan.id,
                kind=plan.kind,
                is_baseline=False,
                created_at=plan.created_at,
                engineers_used_count=plan.engineers_used_count,
                total_mileage_km=plan.total_mileage_km,
            )
            for plan in plans
        )

    async def _build_detail(self, plan: Plan) -> PlanDetailDTO:
        requests = await self._uow.requests.get_by_upload_id(plan.upload_id)
        engineers = await self._uow.engineers.get_by_upload_id(plan.upload_id)
        stops = await self._uow.plan_stops.get_by_plan_id(plan.id)
        unassigned = await self._uow.plan_unassigned_requests.get_by_plan_id(plan.id)

        return PlanPresenter.build_detail(
            plan=plan,
            requests=requests,
            engineers=engineers,
            stops=stops,
            unassigned=unassigned,
            default_shift_start=cfg.planning.default_shift_start,
            default_shift_end=cfg.planning.default_shift_end,
        )
