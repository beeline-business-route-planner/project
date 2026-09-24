import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.db.dto import EngineerCreateDTO
from src.core.db.models import Engineer, EngineerSkill
from src.core.db.repositories.base import BaseRepository


class EngineerRepository(BaseRepository[Engineer]):
    model = Engineer

    async def get_by_id(self, id: object) -> Engineer | None:
        """Переопределяет базовый `session.get` — тому нужен `selectinload` для
        `skills`, иначе доступ к связи после коммита/вне сессии уронит
        `MissingGreenlet` (async ORM не делает ленивую подгрузку неявно)."""
        result = await self._session.scalars(
            select(Engineer).where(Engineer.id == id).options(selectinload(Engineer.skills))
        )
        return result.first()

    async def get_by_upload_id(self, upload_id: uuid.UUID) -> list[Engineer]:
        result = await self._session.scalars(
            select(Engineer)
            .where(Engineer.upload_id == upload_id)
            .options(selectinload(Engineer.skills))
        )
        return list(result.all())

    async def get_by_ids(self, engineer_ids: set[uuid.UUID]) -> list[Engineer]:
        if not engineer_ids:
            return []
        result = await self._session.scalars(
            select(Engineer)
            .where(Engineer.id.in_(engineer_ids))
            .options(selectinload(Engineer.skills))
        )
        return list(result.all())

    async def get_by_ids_for_update(self, engineer_ids: set[uuid.UUID]) -> list[Engineer]:
        if not engineer_ids:
            return []
        result = await self._session.scalars(
            select(Engineer)
            .where(Engineer.id.in_(engineer_ids))
            .order_by(Engineer.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.all())

    def add_many(self, engineers: list[EngineerCreateDTO]) -> None:
        for engineer in engineers:
            model = Engineer()
            model.upload_id = engineer.upload_id
            model.name = engineer.name
            model.region = engineer.region
            model.start_point_address = engineer.start_point_address
            model.start_point_latitude = engineer.start_point_latitude
            model.start_point_longitude = engineer.start_point_longitude
            model.shift_start = engineer.shift_start
            model.shift_end = engineer.shift_end
            model.skills = []
            for skill in engineer.skills:
                engineer_skill = EngineerSkill()
                engineer_skill.skill = skill
                model.skills.append(engineer_skill)
            model.vehicle_type = engineer.vehicle_type
            self.add(model)
