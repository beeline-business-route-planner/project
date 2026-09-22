import uuid

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from src.api.requests.schemas import RequestDetailResponse
from src.api.requests.service import RequestService

router = APIRouter(prefix="/requests", tags=["requests"], route_class=DishkaRoute)


@router.get("/{request_id}", response_model=RequestDetailResponse)
async def get_request(
    service: FromDishka[RequestService], request_id: uuid.UUID
) -> RequestDetailResponse:
    request = await service.get_by_id(request_id)
    return RequestDetailResponse.model_validate(request)
