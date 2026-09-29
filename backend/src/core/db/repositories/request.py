import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from src.core.db.dto import RequestCreateDTO
from src.core.db.enums import Region, RequestStatus
from src.core.db.models import Request
from src.core.db.repositories.base import BaseRepository


class RequestRepository(BaseRepository[Request]):
    model = Request

    async def get_by_upload_id(self, upload_id: uuid.UUID) -> list[Request]:
        result = await self._session.scalars(select(Request).where(Request.upload_id == upload_id))
        return list(result.all())

    async def get_by_ids(self, request_ids: set[uuid.UUID]) -> list[Request]:
        if not request_ids:
            return []
        result = await self._session.scalars(select(Request).where(Request.id.in_(request_ids)))
        return list(result.all())

    async def get_by_ids_for_update(self, request_ids: set[uuid.UUID]) -> list[Request]:
        if not request_ids:
            return []
        result = await self._session.scalars(
            select(Request)
            .where(Request.id.in_(request_ids))
            .order_by(Request.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.all())

    async def list_by_external_id(
        self, region: Region, planning_date: date, external_id: int
    ) -> list[Request]:
        result = await self._session.scalars(
            select(Request).where(
                Request.region == region,
                Request.external_id == external_id,
                Request.window_start >= datetime.combine(planning_date, time.min),
                Request.window_start
                < datetime.combine(planning_date + timedelta(days=1), time.min),
            )
        )
        return list(result.all())

    @staticmethod
    def set_status(request: Request, status: RequestStatus) -> None:
        request.status = status

    def add_many(self, requests: list[RequestCreateDTO]) -> list[Request]:
        models: list[Request] = []
        for request in requests:
            model = Request()
            model.upload_id = request.upload_id
            model.external_id = request.external_id
            model.type_bk = request.type_bk
            model.type_hd = request.type_hd
            model.region = request.region
            model.district = request.district
            model.address = request.address
            model.latitude = request.latitude
            model.longitude = request.longitude
            model.connection_type = request.connection_type
            model.is_gigabit = request.is_gigabit
            model.window_start = request.window_start
            model.window_end = request.window_end
            model.norm_minutes = request.norm_minutes
            model.norm_minutes_without_travel = request.norm_minutes_without_travel
            model.priority = request.priority
            model.required_skill = request.required_skill
            model.required_vehicle_type = request.required_vehicle_type
            self.add(model)
            models.append(model)
        return models
