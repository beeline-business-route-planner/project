import uuid

from sqlalchemy import select

from src.core.db.dto import PlanCreateDTO
from src.core.db.enums import Region
from src.core.db.models import Plan
from src.core.db.repositories.base import BaseRepository


class PlanRepository(BaseRepository[Plan]):
    model = Plan

    async def get_current(self, region: Region) -> Plan | None:
        """Последний неbaseline-план округа — то, что считается "текущим" (см. DATABASE.md)."""
        result = await self._session.scalars(
            select(Plan)
            .where(Plan.region == region, Plan.is_baseline.is_(False))
            .order_by(Plan.created_at.desc())
            .limit(1)
        )
        return result.first()

    async def list_by_region(self, region: Region) -> list[Plan]:
        result = await self._session.scalars(
            select(Plan).where(Plan.region == region).order_by(Plan.created_at.desc())
        )
        return list(result.all())

    def create(self, plan: PlanCreateDTO) -> uuid.UUID:
        plan_id = uuid.uuid7()
        model = Plan()
        model.id = plan_id
        model.region = plan.region
        model.upload_id = plan.upload_id
        model.kind = plan.kind
        model.is_baseline = plan.is_baseline
        model.based_on_plan_id = plan.based_on_plan_id
        model.triggered_by_event_id = plan.triggered_by_event_id
        model.total_mileage_km = plan.total_mileage_km
        model.engineers_used_count = plan.engineers_used_count
        self.add(model)
        return plan_id
