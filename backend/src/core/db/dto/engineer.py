import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Self

from src.core.db.dto.base import BaseDTO
from src.core.db.enums import Region, Skill, VehicleType
from src.core.db.models import Engineer


@dataclass(frozen=True)
class EngineerDTO(BaseDTO):
    """Полная проекция `Engineer` без ORM — максимум полей, важных диспетчеру
    (карточка инженера по клику, см. docs/PLANS_API.md).

    Переопределяет `BaseDTO.from_orm`: `skills` у модели — список `EngineerSkill`
    (связь многие-ко-многим), не голый enum — наивный `getattr` по имени поля
    отдал бы ORM-объекты вместо `Skill`.
    """

    id: uuid.UUID
    name: str
    region: Region
    start_point_address: str
    start_point_latitude: Decimal | None
    start_point_longitude: Decimal | None
    shift_start: datetime
    shift_end: datetime
    skills: tuple[Skill, ...]
    vehicle_type: VehicleType
    created_at: datetime

    @classmethod
    def from_orm(cls, obj: Engineer) -> Self:
        return cls(
            id=obj.id,
            name=obj.name,
            region=obj.region,
            start_point_address=obj.start_point_address,
            start_point_latitude=obj.start_point_latitude,
            start_point_longitude=obj.start_point_longitude,
            shift_start=obj.shift_start,
            shift_end=obj.shift_end,
            skills=tuple(sorted((s.skill for s in obj.skills), key=lambda skill: skill.value)),
            vehicle_type=obj.vehicle_type,
            created_at=obj.created_at,
        )
