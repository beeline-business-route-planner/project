from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from beeline_backend.domain.model import Priority, RequestStatus


class LocationData(BaseModel):
    id: UUID
    address: str
    latitude: float
    longitude: float


class RequestData(BaseModel):
    id: UUID
    external_id: str
    location_id: UUID
    window_start: datetime
    window_end: datetime
    service_minutes: int | None
    full_normative_minutes: int | None
    required_skill: str | None
    required_transport: str | None
    priority: Priority
    status: RequestStatus
    mapping_state: Literal["mapped", "needs_mapping"] = "mapped"


class EngineerData(BaseModel):
    id: UUID
    name: str
    office_location_id: UUID
    shift_start: datetime
    shift_end: datetime
    skills: set[str]
    transport: str
    available_from: datetime
    available_location_id: UUID


class LockedAssignmentData(BaseModel):
    request_id: UUID
    engineer_id: UUID
    position: int
    location_id: UUID
    start_at: datetime
    finish_at: datetime


class TravelCell(BaseModel):
    duration_seconds: int | None = Field(ge=0)
    distance_meters: int | None = Field(ge=0)


class TravelSnapshot(BaseModel):
    provider: str
    provider_version: str
    captured_at: datetime
    profile: str
    cells: list[list[TravelCell]]


class PlanningSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    input_version: str
    dataset_id: UUID
    base_plan_id: UUID | None
    scenario_id: UUID
    planning_date: date
    timezone: str
    as_of: datetime
    locations: list[LocationData]
    location_ids: list[UUID]
    travel_by_profile: dict[str, TravelSnapshot]
    requests: list[RequestData]
    engineers: list[EngineerData]
    locked_assignments: list[LockedAssignmentData]
    execution_snapshot: dict[str, object]
    events: list[dict[str, object]]
    policies: dict[str, object]

    @model_validator(mode="after")
    def matrix_shape_matches_locations(self) -> PlanningSnapshot:
        size = len(self.location_ids)
        if len(set(self.location_ids)) != size:
            raise ValueError("location_ids must be unique")
        for travel in self.travel_by_profile.values():
            if len(travel.cells) != size or any(len(row) != size for row in travel.cells):
                raise ValueError("travel matrix shape must match location_ids")
        return self


class ImportedRequest(BaseModel):
    row_number: int
    external_id: str
    bk_type: str
    hd_type: str
    window_start: datetime
    window_end: datetime
    district: str
    address: str
    gigabit: bool
    connection_kind: str | None = None
    work_code: str | None = None
    service_minutes: int | None = None
    full_normative_minutes: int | None = None
    required_skill: str | None = None
    mapping_state: Literal["mapped", "needs_mapping"]


class ImportIssue(BaseModel):
    file: str
    sheet: str
    row: int | None
    field: str | None
    reason_code: str
    message: str


class ImportedDataset(BaseModel):
    scenario_code: str
    scenario_name: str
    office_address: str
    planning_date: date
    source_name: str
    sha256: str
    requests: list[ImportedRequest]
    issues: list[ImportIssue] = Field(default_factory=list)


class RouteMatrix(BaseModel):
    provider: str
    provider_version: str
    captured_at: datetime
    profile: str
    cells: list[list[TravelCell]]


class ReportAssignment(BaseModel):
    engineer: str
    position: int
    request_external_id: str
    address: str
    planned_start: datetime
    planned_finish: datetime
    confirmed_status: str
    actual_start: datetime | None
    actual_finish: datetime | None
    fact_source: str | None
    distance_meters: int


class DayReport(BaseModel):
    report_version: str
    plan_id: UUID
    scenario: str
    planning_date: date
    generated_at: datetime
    interim: bool
    assignments: list[ReportAssignment]
    metrics: dict[str, float | int | str]

