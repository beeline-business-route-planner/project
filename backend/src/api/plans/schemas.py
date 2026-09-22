import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from src.api.plans.enums import RequestGroupKey
from src.core.db.enums import PlanKind, Region, Skill, UnassignedReason, VehicleType


class EngineerCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    engineer_id: uuid.UUID
    name: str


class RequestTile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: uuid.UUID
    address: str
    district: str
    latitude: Decimal | None
    longitude: Decimal | None
    window_start: datetime
    window_end: datetime
    priority: int
    required_skill: Skill
    planned_start: datetime | None
    planned_finish: datetime | None
    sequence_number: int | None
    assigned_engineer: EngineerCard | None
    unassigned_reason: UnassignedReason | None


class RequestGroup(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    group: RequestGroupKey
    requests: list[RequestTile]


class EngineerTile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    engineer_id: uuid.UUID
    name: str
    vehicle_type: VehicleType
    shift_start: datetime
    shift_end: datetime
    start_latitude: Decimal | None
    start_longitude: Decimal | None
    assigned_requests_count: int
    route_distance_km: Decimal
    stops: list[RequestTile]


class PlanDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    region: Region
    kind: PlanKind
    is_baseline: bool
    created_at: datetime
    based_on_plan_id: uuid.UUID | None
    triggered_by_event_id: uuid.UUID | None
    total_mileage_km: Decimal
    engineers_used_count: int
    request_groups: list[RequestGroup]
    engineers: list[EngineerTile]


class PlanSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: PlanKind
    is_baseline: bool
    created_at: datetime
    engineers_used_count: int
    total_mileage_km: Decimal
