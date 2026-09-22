import uuid

from src.api.exc.requests import RequestNotFoundError
from src.core.db.dto import RequestDTO
from src.core.db.uow import UnitOfWork


class RequestService:
    """Читает одну заявку по id — полная карточка для клика по тайлу плана."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def get_by_id(self, request_id: uuid.UUID) -> RequestDTO:
        request = await self._uow.requests.get_by_id(request_id)
        if request is None:
            raise RequestNotFoundError
        return RequestDTO.from_orm(request)
