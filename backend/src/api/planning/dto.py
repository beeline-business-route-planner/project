import uuid
from dataclasses import dataclass
from datetime import datetime, time

from src.core.db.enums import (
    ConnectionType,
    Region,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    VehicleType,
)


@dataclass(frozen=True)
class PlanningUploadFile:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class PlanningImportResult:
    upload_id: uuid.UUID
    region: Region
    requests_count: int
    engineers_count: int
    plan_id: uuid.UUID | None = None


@dataclass(frozen=True)
class InitialPlanningResult:
    status: str
    imports: tuple[PlanningImportResult, ...]


@dataclass(frozen=True)
class ParsedRequest:
    external_id: int
    type_bk: RequestTypeBk
    type_hd: RequestTypeHd
    district: str
    address: str
    connection_type: ConnectionType | None
    is_gigabit: bool
    window_start: datetime
    window_end: datetime
    norm_minutes: int
    norm_minutes_without_travel: int
    priority: int
    required_skill: Skill


@dataclass(frozen=True)
class ParsedEngineer:
    name: str
    start_point_address: str
    shift_start: time
    shift_end: time
    skills: tuple[Skill, ...]
    vehicle_type: VehicleType


@dataclass(frozen=True)
class ParsedWorkbook:
    source: PlanningUploadFile
    region: Region
    role: str
    office_address: str | None
    requests: tuple[ParsedRequest, ...]
    engineers: tuple[ParsedEngineer, ...]
