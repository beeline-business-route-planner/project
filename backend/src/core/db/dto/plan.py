import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.core.db.enums import PlanKind, Region, UnassignedReason


@dataclass(frozen=True)
class PlanCreateDTO:
    region: Region
    upload_id: uuid.UUID
    kind: PlanKind
    is_baseline: bool
    based_on_plan_id: uuid.UUID | None
    triggered_by_event_id: uuid.UUID | None
    total_mileage_km: Decimal
    engineers_used_count: int


@dataclass(frozen=True)
class PlanStopCreateDTO:
    plan_id: uuid.UUID
    engineer_id: uuid.UUID
    request_id: uuid.UUID
    sequence_number: int
    planned_arrival: datetime
    travel_minutes: int
    distance_km: Decimal
    is_locked: bool


@dataclass(frozen=True)
class PlanUnassignedRequestCreateDTO:
    plan_id: uuid.UUID
    request_id: uuid.UUID
    reason: UnassignedReason
