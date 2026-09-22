import uuid

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from src.api.engineers.schemas import EngineerDetailResponse
from src.api.engineers.service import EngineerService

router = APIRouter(prefix="/engineers", tags=["engineers"], route_class=DishkaRoute)


@router.get("/{engineer_id}", response_model=EngineerDetailResponse)
async def get_engineer(
    service: FromDishka[EngineerService], engineer_id: uuid.UUID
) -> EngineerDetailResponse:
    engineer = await service.get_by_id(engineer_id)
    return EngineerDetailResponse.model_validate(engineer)
