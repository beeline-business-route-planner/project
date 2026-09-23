import uuid

from sqlalchemy import select

from src.core.db.dto import BaselineResultCreateDTO
from src.core.db.models import BaselineResult
from src.core.db.repositories.base import BaseRepository


class BaselineResultRepository(BaseRepository[BaselineResult]):
    model = BaselineResult

    async def get_by_initial_plan_id(self, initial_plan_id: uuid.UUID) -> BaselineResult | None:
        result = await self._session.scalars(
            select(BaselineResult).where(BaselineResult.initial_plan_id == initial_plan_id)
        )
        return result.first()

    def create(self, baseline: BaselineResultCreateDTO) -> uuid.UUID:
        baseline_id = uuid.uuid7()
        model = BaselineResult()
        model.id = baseline_id
        model.initial_plan_id = baseline.initial_plan_id
        model.assigned_requests_count = baseline.assigned_requests_count
        model.unassigned_requests_count = baseline.unassigned_requests_count
        model.engineers_used_count = baseline.engineers_used_count
        model.total_mileage_km = baseline.total_mileage_km
        model.average_workload_with_travel = baseline.average_workload_with_travel
        model.average_workload_without_travel = baseline.average_workload_without_travel
        model.algorithm_version = baseline.algorithm_version
        self.add(model)
        return baseline_id
