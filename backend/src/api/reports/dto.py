import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.core.db.enums import PlanKind, Region, ReplanningEventType, UnassignedReason


@dataclass(frozen=True)
class ReportMetrics:
    requests_count: int
    assigned_count: int
    unassigned_count: int
    engineers_count: int
    engineers_used_count: int
    mileage_km: Decimal
    work_minutes: int
    travel_minutes: int
    utilization_with_travel: Decimal
    utilization_without_travel: Decimal


@dataclass(frozen=True)
class ReportBaseline:
    assigned_count: int
    unassigned_count: int
    engineers_used_count: int
    mileage_km: Decimal
    utilization_with_travel: Decimal
    utilization_without_travel: Decimal


@dataclass(frozen=True)
class ReportPlanVersion:
    id: uuid.UUID
    kind: PlanKind
    approved_at: datetime
    assigned_count: int
    unassigned_count: int
    engineers_used_count: int
    mileage_km: Decimal
    based_on_plan_id: uuid.UUID | None


@dataclass(frozen=True)
class ReportPlanChange:
    previous_plan_id: uuid.UUID
    plan_id: uuid.UUID
    assigned_delta: int
    unassigned_delta: int
    engineers_used_delta: int
    mileage_delta_km: Decimal


@dataclass(frozen=True)
class ReportEvent:
    id: uuid.UUID
    event_type: ReplanningEventType
    occurred_at: datetime
    approved_at: datetime
    target: str


@dataclass(frozen=True)
class ReportStop:
    external_id: int
    address: str
    sequence_number: int
    planned_arrival: datetime
    planned_start: datetime
    planned_finish: datetime
    work_minutes: int
    travel_minutes: int
    distance_km: Decimal
    is_locked: bool


@dataclass(frozen=True)
class ReportEngineer:
    id: uuid.UUID
    name: str
    shift_start: datetime
    shift_end: datetime
    is_available: bool
    work_minutes: int
    travel_minutes: int
    mileage_km: Decimal
    utilization_with_travel: Decimal
    utilization_without_travel: Decimal
    stops: tuple[ReportStop, ...]


@dataclass(frozen=True)
class ReportUnassigned:
    external_id: int
    address: str
    reason: UnassignedReason


@dataclass(frozen=True)
class RegionReportSnapshot:
    region: Region
    planning_date: date
    initial_plan_id: uuid.UUID
    upload_id: uuid.UUID
    initial_approved_at: datetime
    baseline: ReportBaseline
    initial_metrics: ReportMetrics
    plans: tuple[ReportPlanVersion, ...]
    changes: tuple[ReportPlanChange, ...]
    events: tuple[ReportEvent, ...]
    current_plan_id: uuid.UUID
    current_approved_at: datetime
    engineers: tuple[ReportEngineer, ...]
    unassigned: tuple[ReportUnassigned, ...]
    metrics: ReportMetrics


@dataclass(frozen=True)
class DailyReportSnapshot:
    planning_date: date
    generated_at: datetime
    day_in_progress: bool
    regions: tuple[RegionReportSnapshot, ...]
    summary: ReportMetrics
