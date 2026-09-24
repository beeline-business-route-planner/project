import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.api.exc.plans import PlanNotFoundError
from src.api.plans.diff import PlanDiffEngine
from src.api.plans.diff_dto import PlanSnapshotDTO
from src.api.plans.dto import PlanDetailDTO, PlanSummaryDTO
from src.api.plans.presenter import PlanPresenter
from src.api.plans.snapshot import PlanSnapshotAssembler
from src.config import cfg
from src.core.db.enums import ApprovalStatus, PlanKind, Region
from src.core.db.models import Plan
from src.core.db.uow import UnitOfWork


class PlanService:
    """Лениво читает summaries и полные снимки планов с вычисляемым diff."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def get_current(self, region: Region, planning_date: date | None = None) -> PlanDetailDTO:
        target_date = planning_date or datetime.now(ZoneInfo("Europe/Moscow")).date()
        plan = await self._uow.plans.get_current(region, target_date)
        if plan is None:
            raise PlanNotFoundError
        return await self._build_detail(plan, is_current=True)

    async def get_by_id(self, plan_id: uuid.UUID) -> PlanDetailDTO:
        plan = await self._uow.plans.get_by_id(plan_id)
        if plan is None:
            raise PlanNotFoundError
        current = await self._uow.plans.get_current(plan.region, plan.planning_date)
        return await self._build_detail(
            plan, is_current=current is not None and current.id == plan.id
        )

    async def list_by_region(self, region: Region) -> tuple[PlanSummaryDTO, ...]:
        plans = await self._uow.plans.list_by_region(region)
        current_ids = self._current_ids(plans)
        return tuple(self._summary(plan, plan.id in current_ids) for plan in plans)

    async def _build_detail(self, plan: Plan, is_current: bool) -> PlanDetailDTO:
        snapshot = await self._load_snapshot(plan)
        diff = None
        if plan.kind != PlanKind.INITIAL:
            if plan.based_on_plan_id is None:
                raise ValueError("Replan must reference its immutable base plan")
            base = await self._uow.plans.get_by_id(plan.based_on_plan_id)
            if base is None:
                raise PlanNotFoundError
            diff = PlanDiffEngine.compare(await self._load_snapshot(base), snapshot)
        return PlanPresenter.build_detail(
            snapshot=snapshot,
            is_current=is_current,
            approval_deadline=self._approval_deadline(plan),
            diff=diff,
            default_shift_start=cfg.planning.default_shift_start,
            default_shift_end=cfg.planning.default_shift_end,
        )

    async def _load_snapshot(self, plan: Plan) -> PlanSnapshotDTO:
        stops = await self._uow.plan_stops.get_by_plan_id(plan.id)
        unassigned = await self._uow.plan_unassigned_requests.get_by_plan_id(plan.id)
        plan_request_ids = {item.request_id for item in stops} | {
            item.request_id for item in unassigned
        }
        requests = await self._uow.requests.get_by_ids(plan_request_ids)

        engineers = await self._uow.engineers.get_by_upload_id(plan.upload_id)
        loaded_engineer_ids = {item.id for item in engineers}
        stop_engineer_ids = {item.engineer_id for item in stops}
        engineers.extend(
            await self._uow.engineers.get_by_ids(stop_engineer_ids - loaded_engineer_ids)
        )
        engineer_states = await self._uow.plan_engineer_states.get_by_plan_id(plan.id)
        return PlanSnapshotAssembler.build(
            plan, requests, engineers, engineer_states, stops, unassigned
        )

    @staticmethod
    def _summary(plan: Plan, is_current: bool) -> PlanSummaryDTO:
        return PlanSummaryDTO(
            id=plan.id,
            region=plan.region,
            planning_date=plan.planning_date,
            kind=plan.kind,
            approval_status=plan.approval_status,
            created_at=plan.created_at,
            approved_at=plan.approved_at,
            rejected_at=plan.rejected_at,
            approval_deadline=PlanService._approval_deadline(plan),
            based_on_plan_id=plan.based_on_plan_id,
            triggered_by_event_id=plan.triggered_by_event_id,
            is_current=is_current,
            assigned_requests_count=plan.assigned_requests_count,
            unassigned_requests_count=plan.unassigned_requests_count,
            engineers_used_count=plan.engineers_used_count,
            total_mileage_km=plan.total_mileage_km,
        )

    @staticmethod
    def _approval_deadline(plan: Plan) -> datetime | None:
        if plan.approval_status != ApprovalStatus.PENDING:
            return None
        return plan.created_at + timedelta(minutes=cfg.planning.approval_ttl_minutes)

    @staticmethod
    def _current_ids(plans: list[Plan]) -> set[uuid.UUID]:
        current_by_date: dict[date, Plan] = {}
        for plan in plans:
            if plan.approval_status != ApprovalStatus.APPROVED or plan.approved_at is None:
                continue
            current = current_by_date.get(plan.planning_date)
            if current is None or (plan.approved_at, str(plan.id)) > (
                current.approved_at,
                str(current.id),
            ):
                current_by_date[plan.planning_date] = plan
        return {plan.id for plan in current_by_date.values()}
