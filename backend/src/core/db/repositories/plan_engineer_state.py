import uuid

from sqlalchemy import select

from src.core.db.dto import PlanEngineerStateCreateDTO
from src.core.db.models import PlanEngineerState
from src.core.db.repositories.base import BaseRepository


class PlanEngineerStateRepository(BaseRepository[PlanEngineerState]):
    model = PlanEngineerState

    async def get_by_plan_id(self, plan_id: uuid.UUID) -> list[PlanEngineerState]:
        result = await self._session.scalars(
            select(PlanEngineerState).where(PlanEngineerState.plan_id == plan_id)
        )
        return list(result.all())

    def add_many(self, states: list[PlanEngineerStateCreateDTO]) -> None:
        for state in states:
            model = PlanEngineerState()
            model.plan_id = state.plan_id
            model.engineer_id = state.engineer_id
            model.is_available = state.is_available
            self.add(model)
