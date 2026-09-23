import uuid
from datetime import date, datetime

from sqlalchemy import select, update

from src.core.db.dto import PlanCreateDTO
from src.core.db.enums import ApprovalStatus, PlanKind, Region
from src.core.db.models import Plan
from src.core.db.repositories.base import BaseRepository


class PlanRepository(BaseRepository[Plan]):
    model = Plan

    async def get_current(self, region: Region, planning_date: date) -> Plan | None:
        """Последний утверждённый план округа за рабочий день."""
        result = await self._session.scalars(
            select(Plan)
            .where(
                Plan.region == region,
                Plan.planning_date == planning_date,
                Plan.approval_status == ApprovalStatus.APPROVED,
            )
            .order_by(Plan.approved_at.desc(), Plan.id.desc())
            .limit(1)
        )
        return result.first()

    async def list_by_region(self, region: Region) -> list[Plan]:
        result = await self._session.scalars(
            select(Plan)
            .where(Plan.region == region)
            .order_by(Plan.created_at.desc(), Plan.id.desc())
        )
        return list(result.all())

    async def get_with_lock(self, plan_id: uuid.UUID) -> Plan | None:
        result = await self._session.scalars(
            select(Plan).where(Plan.id == plan_id).with_for_update()
        )
        return result.first()

    async def list_pending(
        self, region: Region, planning_date: date, exclude_plan_id: uuid.UUID | None = None
    ) -> list[Plan]:
        query = select(Plan).where(
            Plan.region == region,
            Plan.planning_date == planning_date,
            Plan.approval_status == ApprovalStatus.PENDING,
        )
        if exclude_plan_id is not None:
            query = query.where(Plan.id != exclude_plan_id)
        result = await self._session.scalars(query.order_by(Plan.created_at.desc(), Plan.id.desc()))
        return list(result.all())

    async def reject_pending(
        self,
        region: Region,
        planning_date: date,
        rejected_at: datetime,
        exclude_plan_id: uuid.UUID | None = None,
    ) -> int:
        query = (
            update(Plan)
            .where(
                Plan.region == region,
                Plan.planning_date == planning_date,
                Plan.approval_status == ApprovalStatus.PENDING,
            )
            .values(approval_status=ApprovalStatus.REJECTED, rejected_at=rejected_at)
        )
        if exclude_plan_id is not None:
            query = query.where(Plan.id != exclude_plan_id)
        result = await self._session.execute(query)
        return result.rowcount  # type: ignore[attr-defined]

    async def has_approved_initial(self, region: Region, planning_date: date) -> bool:
        result = await self._session.scalar(
            select(Plan.id)
            .where(
                Plan.region == region,
                Plan.planning_date == planning_date,
                Plan.kind == PlanKind.INITIAL,
                Plan.approval_status == ApprovalStatus.APPROVED,
            )
            .limit(1)
        )
        return result is not None

    @staticmethod
    def set_approval_status(
        plan: Plan, status: ApprovalStatus, decided_at: datetime | None
    ) -> None:
        plan.approval_status = status
        plan.approved_at = decided_at if status == ApprovalStatus.APPROVED else None
        plan.rejected_at = decided_at if status == ApprovalStatus.REJECTED else None

    def create(self, plan: PlanCreateDTO) -> uuid.UUID:
        plan_id = uuid.uuid7()
        model = Plan()
        model.id = plan_id
        model.region = plan.region
        model.planning_date = plan.planning_date
        model.upload_id = plan.upload_id
        model.kind = plan.kind
        model.approval_status = ApprovalStatus.PENDING
        model.based_on_plan_id = plan.based_on_plan_id
        model.triggered_by_event_id = plan.triggered_by_event_id
        model.calculation_cutoff_at = plan.calculation_cutoff_at
        model.total_mileage_km = plan.total_mileage_km
        model.engineers_used_count = plan.engineers_used_count
        model.assigned_requests_count = plan.assigned_requests_count
        model.unassigned_requests_count = plan.unassigned_requests_count
        self.add(model)
        return plan_id
