import uuid

from src.api.exc.engineers import EngineerNotFoundError
from src.core.db.dto import EngineerDTO
from src.core.db.uow import UnitOfWork


class EngineerService:
    """Читает одного инженера по id — полная карточка для клика по тайлу плана."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def get_by_id(self, engineer_id: uuid.UUID) -> EngineerDTO:
        engineer = await self._uow.engineers.get_by_id(engineer_id)
        if engineer is None:
            raise EngineerNotFoundError
        return EngineerDTO.from_orm(engineer)
