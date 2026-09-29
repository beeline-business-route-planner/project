import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.core.db.enums import (
    DistributionMode,
    PlanKind,
    PlanStrategy,
    Region,
    UnassignedReason,
)


@dataclass(frozen=True)
class PlanCreateDTO:
    region: Region
    planning_date: date
    upload_id: uuid.UUID
    kind: PlanKind
    based_on_plan_id: uuid.UUID | None
    triggered_by_event_id: uuid.UUID | None
    calculation_cutoff_at: datetime
    mode: DistributionMode
    strategy: PlanStrategy
    total_mileage_km: Decimal
    engineers_used_count: int
    assigned_requests_count: int
    unassigned_requests_count: int
    created_at: datetime | None = None
    edited_from_plan_id: uuid.UUID | None = None


@dataclass(frozen=True)
class PlanStopCreateDTO:
    plan_id: uuid.UUID
    engineer_id: uuid.UUID
    request_id: uuid.UUID
    sequence_number: int
    planned_arrival: datetime
    planned_start: datetime
    planned_finish: datetime
    travel_minutes: int
    distance_km: Decimal
    is_locked: bool


@dataclass(frozen=True)
class PlanEngineerStateCreateDTO:
    plan_id: uuid.UUID
    engineer_id: uuid.UUID
    is_available: bool


@dataclass(frozen=True)
class PlanUnassignedRequestCreateDTO:
    plan_id: uuid.UUID
    request_id: uuid.UUID
    reason: UnassignedReason


@dataclass(frozen=True)
class BaselineResultCreateDTO:
    initial_plan_id: uuid.UUID
    assigned_requests_count: int
    unassigned_requests_count: int
    engineers_used_count: int
    total_mileage_km: Decimal
    average_workload_with_travel: Decimal
    average_workload_without_travel: Decimal
    algorithm_version: str
