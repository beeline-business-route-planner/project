import uuid

from src.core.db.dto import PlanCreateDTO
from src.core.db.models import Plan
from src.core.db.repositories.base import BaseRepository


class PlanRepository(BaseRepository[Plan]):
    model = Plan

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
