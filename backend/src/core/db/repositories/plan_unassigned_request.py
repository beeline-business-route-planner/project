from src.core.db.dto import PlanUnassignedRequestCreateDTO
from src.core.db.models import PlanUnassignedRequest
from src.core.db.repositories.base import BaseRepository


class PlanUnassignedRequestRepository(BaseRepository[PlanUnassignedRequest]):
    model = PlanUnassignedRequest

    def add_many(self, items: list[PlanUnassignedRequestCreateDTO]) -> None:
        for item in items:
            model = PlanUnassignedRequest()
            model.plan_id = item.plan_id
            model.request_id = item.request_id
            model.reason = item.reason
            self.add(model)
