from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from beeline_backend.domain.model import RequestStatus


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    correlation_id: str


class PlanningRequest(BaseModel):
    scenario_id: UUID
    planning_date: date
    base_plan_id: UUID | None = None
    as_of: datetime | None = None

    @model_validator(mode="after")
    def aware_as_of(self) -> PlanningRequest:
        if self.as_of is not None and (
            self.as_of.tzinfo is None or self.as_of.utcoffset() is None
        ):
            raise ValueError("as_of must contain a timezone offset")
        return self


class ReplanningRequest(PlanningRequest):
    base_plan_id: UUID


class ApprovalRequest(BaseModel):
    expected_base_plan_id: UUID | None = None
    actor: str = Field(min_length=1, max_length=160)


class FactRequest(BaseModel):
    status: RequestStatus
    effective_at: datetime
    actor: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=1000)
    actual_start: datetime | None = None
    actual_finish: datetime | None = None

    @model_validator(mode="after")
    def valid_actual_times(self) -> FactRequest:
        for field_name in ("effective_at", "actual_start", "actual_finish"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must contain a timezone offset")
        if self.actual_start and self.actual_finish and self.actual_finish < self.actual_start:
            raise ValueError("actual_finish cannot precede actual_start")
        return self


class DayEventRequest(BaseModel):
    scenario_id: UUID
    planning_date: date
    event_type: Literal["urgent_request", "request_cancelled", "engineer_unavailable", "fact_changed"]
    effective_at: datetime
    payload: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=255)
    actor: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def aware_effective_at(self) -> DayEventRequest:
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must contain a timezone offset")
        return self


class NewRequest(BaseModel):
    scenario_id: UUID
    planning_date: date
    external_id: str = Field(min_length=1, max_length=128)
    address: str = Field(min_length=3, max_length=1000)
    district: str = Field(min_length=1, max_length=255)
    window_start: datetime
    window_end: datetime
    service_minutes: int = Field(gt=0, le=24 * 60)
    required_skill: Literal["connection", "emergency", "local"]
    required_transport: Literal["car", "walking", "bicycle", "transit"] | None = None
    priority: Literal["normal", "urgent"] = "normal"
    idempotency_key: str = Field(min_length=1, max_length=255)
    actor: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def valid_window(self) -> NewRequest:
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.window_start, self.window_end)
        ):
            raise ValueError("window timestamps must contain a timezone offset")
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


class ManualChangeRequest(BaseModel):
    request_id: UUID
    engineer_id: UUID
    position: int = Field(gt=0)
    start_at: datetime | None = None
    reason: str = Field(min_length=1, max_length=1000)
    actor: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def aware_start_at(self) -> ManualChangeRequest:
        if self.start_at is not None and (
            self.start_at.tzinfo is None or self.start_at.utcoffset() is None
        ):
            raise ValueError("start_at must contain a timezone offset")
        return self


class StatusResponse(BaseModel):
    status: str


class ImportIssueResponse(BaseModel):
    file: str
    sheet: str
    row: int | None = None
    field: str | None = None
    reason_code: str
    message: str


class ImportResponse(BaseModel):
    dataset_id: UUID
    scenario_id: UUID
    duplicate: bool
    request_count: int | None = None
    issues: list[ImportIssueResponse] = Field(default_factory=list)


class ScenarioResponse(BaseModel):
    id: UUID
    code: str
    name: str
    timezone: str
    planning_dates: list[date]


class RequestListItemResponse(BaseModel):
    id: UUID
    external_id: str
    address: str
    coordinates: list[float | None]
    window_start: datetime
    window_end: datetime
    service_minutes: int | None
    priority: str
    required_skills: list[str]
    required_transport: str | None = None
    sla_deadline: datetime
    status: RequestStatus
    mapping_state: str


class StatusEventResponse(BaseModel):
    id: UUID
    status: RequestStatus
    source: str
    actor: str
    effective_at: datetime
    recorded_at: datetime
    reason: str


class RequestDetailResponse(BaseModel):
    id: UUID
    external_id: str
    bk_type: str
    hd_type: str
    address: str
    coordinates: list[float]
    window_start: datetime
    window_end: datetime
    service_minutes: int | None
    full_normative_minutes: int | None
    priority: str
    required_skills: list[str]
    required_transport: str | None = None
    sla_deadline: datetime
    mapping_state: str
    status_history: list[StatusEventResponse]


class EngineerStartLocationResponse(BaseModel):
    id: UUID
    address: str
    coordinates: list[float | None]


class EngineerResponse(BaseModel):
    id: UUID
    external_code: str
    name: str
    transport: str
    skills: list[str]
    work_start: time | None = None
    work_end: time | None = None
    availability: bool
    start_location: EngineerStartLocationResponse | None = None


class PlanningResultResponse(BaseModel):
    planning_run_id: UUID
    plan_id: UUID
    status: str
    duplicate: bool = False


class PlanningFailureResponse(BaseModel):
    code: str
    message: str | None = None


class PlanningRunResponse(BaseModel):
    id: UUID
    status: str
    algorithm: str
    input_version: str
    plan_id: UUID | None = None
    failure: PlanningFailureResponse | None = None
    started_at: datetime
    finished_at: datetime | None = None


class PlanSummaryResponse(BaseModel):
    id: UUID
    status: str
    parent_plan_id: UUID | None = None
    base_plan_id: UUID | None = None
    input_version: str
    created_at: datetime


class AssignmentResponse(BaseModel):
    request_id: UUID
    request_external_id: str
    engineer_id: UUID
    engineer: str
    position: int
    address: str
    arrival_at: datetime
    start_at: datetime
    finish_at: datetime
    travel_seconds: int
    distance_meters: int
    explanation: str
    reasons: list[str]


class UnassignedResponse(BaseModel):
    request_id: UUID
    request_external_id: str
    reason_code: str
    explanation: str


class ViolationResponse(BaseModel):
    type: str
    request_id: UUID | None = None
    details: dict[str, object] = Field(default_factory=dict)


class GeoJsonLineStringResponse(BaseModel):
    type: Literal["LineString"]
    coordinates: list[list[float]]
    provider: str | None = None


class PlanRouteResponse(BaseModel):
    engineer_id: UUID
    profile: str
    geometry: GeoJsonLineStringResponse


MetricValue = float | int | str | None


class PlanResponse(BaseModel):
    id: UUID
    scenario_id: UUID
    planning_date: date
    status: str
    parent_plan_id: UUID | None = None
    base_plan_id: UUID | None = None
    input_version: str
    assignments: list[AssignmentResponse]
    unassigned: list[UnassignedResponse]
    violations: list[ViolationResponse]
    metrics: dict[str, MetricValue]
    routes: list[PlanRouteResponse]
    warnings: list[str]


class EngineerRouteResponse(BaseModel):
    plan_id: UUID
    engineer_id: UUID
    stops: list[AssignmentResponse]
    route: PlanRouteResponse | None = None
    assigned_requests_count: int
    workload_seconds: int
    route_distance_meters: int
    route_duration_seconds: int
    sla_violations: int


class ApprovalResponse(BaseModel):
    plan_id: UUID
    status: str
    approved_at: datetime


class FactResponse(BaseModel):
    event_id: UUID
    request_id: UUID
    status: RequestStatus


class NewRequestResponse(BaseModel):
    request_id: UUID
    event_id: UUID
    duplicate: bool


class DayEventResponse(BaseModel):
    event_id: UUID
    duplicate: bool
    replanning: PlanningResultResponse | None = None


class ManualChangeResponse(BaseModel):
    plan_id: UUID
    status: str
    parent_plan_id: UUID


class PlanMetricsResponse(BaseModel):
    plan_id: UUID
    metrics: dict[str, MetricValue]
    unassigned: list[UnassignedResponse]


class AssignmentDiffResponse(BaseModel):
    engineer_id: UUID
    position: int
    start_at: datetime
    finish_at: datetime
    from_location_id: UUID
    location_id: UUID
    distance_meters: int


class PlanDiffItemResponse(BaseModel):
    request_id: UUID
    changes: list[str]
    old: AssignmentDiffResponse | None = None
    new: AssignmentDiffResponse | None = None


class PlanDiffResponse(BaseModel):
    old_plan_id: UUID
    new_plan_id: UUID
    summary: dict[str, int]
    items: list[PlanDiffItemResponse]


class PlanChangeResponse(BaseModel):
    request_id: UUID
    type: Literal[
        "ASSIGNED", "UNASSIGNED", "REASSIGNED", "TIME_CHANGED", "ROUTE_CHANGED"
    ]
    from_engineer_id: UUID | None = None
    to_engineer_id: UUID | None = None


class PlanChangesResponse(BaseModel):
    base_plan_id: UUID
    new_plan_id: UUID
    changes: list[PlanChangeResponse]


class AuditResponse(BaseModel):
    id: UUID
    action: str
    actor: str
    source: str
    effective_at: datetime
    recorded_at: datetime
    object_type: str
    object_id: UUID | None = None
    reason: str | None = None
    details: dict[str, object]


class DashboardResponse(BaseModel):
    scenario_id: UUID
    planning_date: date
    active_plan: PlanResponse | None = None
    requests: list[RequestListItemResponse]
    engineers: list[EngineerResponse]
