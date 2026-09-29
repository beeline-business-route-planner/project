import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.api.plans.enums import EngineerChange, RequestChange
from src.core.db.enums import (
    ApprovalStatus,
    ConnectionType,
    PlanKind,
    Region,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    UnassignedReason,
    VehicleType,
)


@dataclass(frozen=True)
class SnapshotRequestDTO:
    request_id: uuid.UUID
    external_id: int
    address: str
    district: str
    latitude: Decimal | None
    longitude: Decimal | None
    window_start: datetime
    window_end: datetime
    priority: int
    required_skill: Skill
    service_minutes: int
    engineer_id: uuid.UUID | None
    sequence_number: int | None
    planned_arrival: datetime | None
    planned_start: datetime | None
    planned_finish: datetime | None
    travel_minutes: int | None
    distance_km: Decimal | None
    is_locked: bool
    unassigned_reason: UnassignedReason | None
    upload_id: uuid.UUID | None = None
    type_bk: RequestTypeBk | None = None
    type_hd: RequestTypeHd | None = None
    connection_type: ConnectionType | None = None
    is_gigabit: bool | None = None
    norm_minutes: int | None = None


@dataclass(frozen=True)
class SnapshotEngineerDTO:
    engineer_id: uuid.UUID
    name: str
    vehicle_type: VehicleType
    shift_start: datetime
    shift_end: datetime
    start_latitude: Decimal | None
    start_longitude: Decimal | None
    is_available: bool
    route_distance_km: Decimal
    workload_without_travel: Decimal
    workload_with_travel: Decimal
    requests: tuple[SnapshotRequestDTO, ...]


@dataclass(frozen=True)
class PlanMetricsDTO:
    assigned_requests_count: int
    unassigned_requests_count: int
    engineers_used_count: int
    available_engineers_count: int
    total_mileage_km: Decimal
    total_work_minutes: int
    total_travel_minutes: int
    average_workload_without_travel: Decimal
    average_workload_with_travel: Decimal
    average_used_workload_without_travel: Decimal
    average_used_workload_with_travel: Decimal
    min_workload_with_travel: Decimal
    max_workload_with_travel: Decimal


@dataclass(frozen=True)
class PlanSnapshotDTO:
    id: uuid.UUID
    region: Region
    planning_date: date
    kind: PlanKind
    approval_status: ApprovalStatus
    created_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    calculation_cutoff_at: datetime
    based_on_plan_id: uuid.UUID | None
    triggered_by_event_id: uuid.UUID | None
    metrics: PlanMetricsDTO
    requests: tuple[SnapshotRequestDTO, ...]
    engineers: tuple[SnapshotEngineerDTO, ...]
    edited_from_plan_id: uuid.UUID | None = None


@dataclass(frozen=True)
class IntMetricDeltaDTO:
    before: int
    after: int
    delta: int


@dataclass(frozen=True)
class DecimalMetricDeltaDTO:
    before: Decimal
    after: Decimal
    delta: Decimal


@dataclass(frozen=True)
class PlanSummaryDiffDTO:
    assigned_requests: IntMetricDeltaDTO
    unassigned_requests: IntMetricDeltaDTO
    engineers_used: IntMetricDeltaDTO
    total_work_minutes: IntMetricDeltaDTO
    total_travel_minutes: IntMetricDeltaDTO
    total_mileage_km: DecimalMetricDeltaDTO
    average_workload_without_travel: DecimalMetricDeltaDTO
    average_workload_with_travel: DecimalMetricDeltaDTO


@dataclass(frozen=True)
class RequestDiffDTO:
    request_id: uuid.UUID
    changes: tuple[RequestChange, ...]
    before: SnapshotRequestDTO | None
    after: SnapshotRequestDTO | None


@dataclass(frozen=True)
class EngineerDiffDTO:
    engineer_id: uuid.UUID
    change: EngineerChange
    before: SnapshotEngineerDTO | None
    after: SnapshotEngineerDTO | None
    requests: tuple[RequestDiffDTO, ...]


@dataclass(frozen=True)
class PlanDiffDTO:
    base_plan_id: uuid.UUID
    candidate_plan_id: uuid.UUID
    summary: PlanSummaryDiffDTO
    engineers: tuple[EngineerDiffDTO, ...]
    requests: tuple[RequestDiffDTO, ...]
