import uuid

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from src.api.requests.schemas import RequestDetailResponse, RequestStatusUpdateRequest
from src.api.requests.service import RequestService

router = APIRouter(prefix="/requests", tags=["requests"], route_class=DishkaRoute)


@router.get("/{request_id}", response_model=RequestDetailResponse)
async def get_request(
    service: FromDishka[RequestService], request_id: uuid.UUID
) -> RequestDetailResponse:
    request = await service.get_by_id(request_id)
    return RequestDetailResponse.model_validate(request)


@router.patch("/{request_id}/status", response_model=RequestDetailResponse)
async def update_request_status(
    service: FromDishka[RequestService], request_id: uuid.UUID, body: RequestStatusUpdateRequest
) -> RequestDetailResponse:
    request = await service.update_status(request_id, body.status)
    return RequestDetailResponse.model_validate(request)
