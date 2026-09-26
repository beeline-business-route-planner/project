import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from src.core.db.enums import Region, Skill, VehicleType


class EngineerDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    is_available: bool
    created_at: datetime
