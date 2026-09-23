import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.core.db.dto.base import BaseDTO
from src.core.db.enums import (
    ConnectionType,
    Region,
    RequestStatus,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    VehicleType,
)


@dataclass(frozen=True)
class RequestDTO(BaseDTO):
    """Полная проекция `Request` без ORM — максимум полей, важных диспетчеру
    (карточка заявки по клику на тайл плана, см. docs/PLANS_API.md)."""

    id: uuid.UUID
    external_id: int
    type_bk: RequestTypeBk
    type_hd: RequestTypeHd
    region: Region
    district: str
    address: str
    latitude: Decimal | None
    longitude: Decimal | None
    connection_type: ConnectionType | None
    is_gigabit: bool
    window_start: datetime
    window_end: datetime
    norm_minutes: int
    norm_minutes_without_travel: int
    priority: int
    required_skill: Skill
    required_vehicle_type: VehicleType | None
    status: RequestStatus
    created_at: datetime
