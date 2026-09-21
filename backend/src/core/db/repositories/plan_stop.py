from src.core.db.dto import PlanStopCreateDTO
from src.core.db.models import PlanStop
from src.core.db.repositories.base import BaseRepository


class PlanStopRepository(BaseRepository[PlanStop]):
    model = PlanStop

    def add_many(self, stops: list[PlanStopCreateDTO]) -> None:
        for stop in stops:
            model = PlanStop()
            model.plan_id = stop.plan_id
            model.engineer_id = stop.engineer_id
            model.request_id = stop.request_id
            model.sequence_number = stop.sequence_number
            model.planned_arrival = stop.planned_arrival
            model.travel_minutes = stop.travel_minutes
            model.distance_km = stop.distance_km
            model.is_locked = stop.is_locked
            self.add(model)
