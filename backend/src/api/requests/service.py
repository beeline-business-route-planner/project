import uuid

from src.api.exc.requests import (
    RequestAlreadyCancelledError,
    RequestCancelViaStatusError,
    RequestNotFoundError,
)
from src.core.db.dto import RequestDTO
from src.core.db.enums import RequestStatus
from src.core.db.uow import UnitOfWork


class RequestService:
    """Карточка заявки и ручная корректировка её статуса диспетчером."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def get_by_id(self, request_id: uuid.UUID) -> RequestDTO:
        request = await self._uow.requests.get_by_id(request_id)
        if request is None:
            raise RequestNotFoundError
        return RequestDTO.from_orm(request)

    async def update_status(self, request_id: uuid.UUID, status: RequestStatus) -> RequestDTO:
        """Меняет статус заявки; по нему replan решает, какие остановки уже нельзя менять.

        Отмена идёт только через внештатное событие: она порождает план с отменой.

        Raises:
            RequestNotFoundError: если заявки нет.
            RequestCancelViaStatusError: если запрошен статус `cancelled`.
            RequestAlreadyCancelledError: если заявка уже отменена.
        """

        if status == RequestStatus.CANCELLED:
            raise RequestCancelViaStatusError
        try:
            requests = await self._uow.requests.get_by_ids_for_update({request_id})
            if not requests:
                raise RequestNotFoundError
            request = requests[0]
            if request.status == RequestStatus.CANCELLED:
                raise RequestAlreadyCancelledError
            self._uow.requests.set_status(request, status)
            await self._uow.flush()
            result = RequestDTO.from_orm(request)
            await self._uow.commit()
            return result
        except Exception:
            await self._uow.rollback()
            raise
