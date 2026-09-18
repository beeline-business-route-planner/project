from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db.models.base import Base


class BaseRepository[ModelType: Base]:
    model: type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: object) -> ModelType | None:
        return await self._session.get(self.model, id)

    def add(self, obj: ModelType) -> None:
        self._session.add(obj)

    async def delete(self, obj: ModelType) -> None:
        await self._session.delete(obj)
