import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from src.api.plans.enums import EngineerChange, RequestChange, RequestGroupKey
from src.core.db.enums import (
    ApprovalStatus,
    PlanKind,
    Region,
    Skill,
    UnassignedReason,
    VehicleType,
)
from src.core.utils.time import as_utc


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EngineerCard(ApiModel):
    engineer_id: uuid.UUID
    name: str


class RequestTile(ApiModel):
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
    planned_arrival: datetime | None
    planned_start: datetime | None
    planned_finish: datetime | None
    sequence_number: int | None
    travel_minutes: int | None
    distance_km: Decimal | None
    is_locked: bool
    assigned_engineer: EngineerCard | None
    unassigned_reason: UnassignedReason | None


class RequestGroup(ApiModel):
    group: RequestGroupKey
    requests: list[RequestTile]


class EngineerTile(ApiModel):
    engineer_id: uuid.UUID
    name: str
    vehicle_type: VehicleType
    shift_start: datetime
    shift_end: datetime
    start_latitude: Decimal | None
    start_longitude: Decimal | None
    assigned_requests_count: int
    route_distance_km: Decimal
    workload_without_travel: Decimal
    workload_with_travel: Decimal
    stops: list[RequestTile]


class PlanMetrics(ApiModel):
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


class SnapshotRequest(ApiModel):
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


class SnapshotEngineer(ApiModel):
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
    requests: list[SnapshotRequest]


class IntMetricDelta(ApiModel):
    before: int
    after: int
    delta: int


class DecimalMetricDelta(ApiModel):
    before: Decimal
    after: Decimal
    delta: Decimal


class PlanSummaryDiff(ApiModel):
    assigned_requests: IntMetricDelta
    unassigned_requests: IntMetricDelta
    engineers_used: IntMetricDelta
    total_work_minutes: IntMetricDelta
    total_travel_minutes: IntMetricDelta
    total_mileage_km: DecimalMetricDelta
    average_workload_without_travel: DecimalMetricDelta
    average_workload_with_travel: DecimalMetricDelta


class RequestDiff(ApiModel):
    request_id: uuid.UUID
    changes: list[RequestChange]
    before: SnapshotRequest | None
    after: SnapshotRequest | None


class EngineerDiff(ApiModel):
    engineer_id: uuid.UUID
    change: EngineerChange
    before: SnapshotEngineer | None
    after: SnapshotEngineer | None
    requests: list[RequestDiff]


class PlanDiff(ApiModel):
    base_plan_id: uuid.UUID
    candidate_plan_id: uuid.UUID
    summary: PlanSummaryDiff
    engineers: list[EngineerDiff]
    requests: list[RequestDiff]


class BaselineMetrics(ApiModel):
    assigned_requests_count: int
    unassigned_requests_count: int
    engineers_used_count: int
    total_mileage_km: Decimal
    average_workload_with_travel: Decimal
    average_workload_without_travel: Decimal
    algorithm_version: str


class PlanLifecycleResponse(ApiModel):
    @field_validator(
        "created_at", "approved_at", "rejected_at", "approval_deadline", check_fields=False
    )
    @classmethod
    def attach_utc(cls, value: datetime | None) -> datetime | None:
        return as_utc(value)


class PlanDetailResponse(PlanLifecycleResponse):
    id: uuid.UUID
    region: Region
    planning_date: date
    kind: PlanKind
    approval_status: ApprovalStatus
    created_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    approval_deadline: datetime | None
    is_current: bool
    can_approve: bool
    can_reject: bool
    calculation_cutoff_at: datetime
    based_on_plan_id: uuid.UUID | None
    triggered_by_event_id: uuid.UUID | None
    metrics: PlanMetrics
    baseline_metrics: BaselineMetrics | None
    request_groups: list[RequestGroup]
    engineers: list[EngineerTile]
    diff: PlanDiff | None


class PlanSummaryResponse(PlanLifecycleResponse):
    id: uuid.UUID
    region: Region
    planning_date: date
    kind: PlanKind
    approval_status: ApprovalStatus
    created_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    approval_deadline: datetime | None
    based_on_plan_id: uuid.UUID | None
    triggered_by_event_id: uuid.UUID | None
    is_current: bool
    assigned_requests_count: int
    unassigned_requests_count: int
    engineers_used_count: int
    total_mileage_km: Decimal
