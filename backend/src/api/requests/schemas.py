import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from src.core.db.enums import (
    ConnectionType,
    Region,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    VehicleType,
)


class RequestDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    created_at: datetime
