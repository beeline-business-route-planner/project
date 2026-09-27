import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.core.db.enums import (
    ConnectionType,
    Region,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    VehicleType,
)


@dataclass(frozen=True)
class UploadedFileCreateDTO:
    upload_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    s3_bucket: str
    s3_key: str


@dataclass(frozen=True)
class RequestCreateDTO:
    upload_id: uuid.UUID
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


@dataclass(frozen=True)
class EngineerCreateDTO:
    upload_id: uuid.UUID
    name: str
    region: Region
    start_point_address: str
    start_point_latitude: Decimal
    start_point_longitude: Decimal
    shift_start: datetime
    shift_end: datetime
    skills: tuple[Skill, ...]
    vehicle_type: VehicleType
