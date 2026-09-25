import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

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
class InitialPlanSummary:
    id: uuid.UUID
    region: Region
    planning_date: date
    created_at: datetime
    approval_deadline: datetime
    assigned_requests_count: int
    unassigned_requests_count: int
    engineers_used_count: int
    total_mileage_km: Decimal


@dataclass(frozen=True)
class PlanningRegionResult:
    region: Region
    status: Literal["success", "error"]
    plan_summary: InitialPlanSummary | None = None
    error_code: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class InitialPlanningResult:
    status: Literal["success", "partial_success", "error"]
    regions: tuple[PlanningRegionResult, ...]


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
