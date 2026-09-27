import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.db.enums import (
    ApprovalStatus,
    ConnectionType,
    PlanKind,
    Region,
    ReplanningEventType,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    VehicleType,
)
from src.core.utils.time import as_utc


class InitialPlanSummaryResponse(BaseModel):
    id: uuid.UUID
    region: Region
    kind: PlanKind = PlanKind.INITIAL
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    planning_date: date
    created_at: datetime
    approval_deadline: datetime
    assigned_requests_count: int
    unassigned_requests_count: int
    engineers_used_count: int
    total_mileage_km: Decimal

    @field_validator("created_at", "approval_deadline")
    @classmethod
    def attach_utc(cls, value: datetime) -> datetime:
        return as_utc(value)


class PlanningRegionErrorResponse(BaseModel):
    code: str
    detail: str


class PlanningRegionResponse(BaseModel):
    region: Region
    status: Literal["success", "error"]
    plan_summary: InitialPlanSummaryResponse | None = None
    error: PlanningRegionErrorResponse | None = None


class InitialPlanningResponse(BaseModel):
    status: Literal["success", "partial_success", "error"]
    regions: list[PlanningRegionResponse]


class ReplanPlanningRequest(BaseModel):
    regions: list[Region]

    @model_validator(mode="after")
    def validate_regions(self) -> ReplanPlanningRequest:
        if not self.regions or len(self.regions) != len(set(self.regions)):
            raise ValueError("Нужен непустой список уникальных округов")
        return self


class ReplanPlanSummaryResponse(BaseModel):
    id: uuid.UUID
    region: Region
    kind: PlanKind = PlanKind.REPLAN
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    planning_date: date
    created_at: datetime
    based_on_plan_id: uuid.UUID
    assigned_requests_count: int
    unassigned_requests_count: int
    engineers_used_count: int
    total_mileage_km: Decimal

    @field_validator("created_at")
    @classmethod
    def attach_utc(cls, value: datetime) -> datetime:
        return as_utc(value)


class ReplanRegionResponse(BaseModel):
    region: Region
    status: Literal["success", "error"]
    plan_summary: ReplanPlanSummaryResponse | None = None
    error: PlanningRegionErrorResponse | None = None


class ReplanPlanningResponse(BaseModel):
    status: Literal["success", "partial_success", "error"]
    regions: list[ReplanRegionResponse]


class UrgentRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: int = Field(gt=0)
    type_bk: RequestTypeBk
    type_hd: RequestTypeHd
    district: str = Field(min_length=1, max_length=255)
    address: str = Field(min_length=1, max_length=512)
    connection_type: ConnectionType | None = None
    is_gigabit: bool
    window_start: datetime
    window_end: datetime
    norm_minutes: int = Field(gt=0, le=32767)
    norm_minutes_without_travel: int = Field(gt=0, le=32767)
    priority: Literal[1, 2]
    required_skill: Skill
    required_vehicle_type: VehicleType | None = None

    @field_validator("district", "address")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Район и адрес должны содержать текст")
        return value.strip()

    @model_validator(mode="after")
    def validate_window(self) -> UrgentRequestPayload:
        if self.window_start.tzinfo or self.window_end.tzinfo:
            raise ValueError("Окно заявки должно быть локальным временем Москвы без timezone")
        if self.window_end <= self.window_start:
            raise ValueError("Конец окна должен быть позже начала")
        if self.norm_minutes_without_travel > self.norm_minutes:
            raise ValueError("Время работы не может превышать полный норматив")
        return self


class EventPlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: Region
    event_type: ReplanningEventType
    request_id: uuid.UUID | None = None
    engineer_id: uuid.UUID | None = None
    urgent_request: UrgentRequestPayload | None = None

    @model_validator(mode="after")
    def validate_target(self) -> EventPlanningRequest:
        if self.event_type == ReplanningEventType.URGENT_REQUEST:
            valid = (
                self.urgent_request is not None
                and self.request_id is None
                and self.engineer_id is None
            )
        elif self.event_type == ReplanningEventType.REQUEST_CANCELLED:
            valid = (
                self.request_id is not None
                and self.engineer_id is None
                and self.urgent_request is None
            )
        else:
            valid = (
                self.engineer_id is not None
                and self.request_id is None
                and self.urgent_request is None
            )
        if not valid:
            raise ValueError("Укажите ровно один payload для типа события")
        return self


class EventPlanSummaryResponse(ReplanPlanSummaryResponse):
    kind: PlanKind = PlanKind.EVENT_REPLAN


class EventPlanningResponse(BaseModel):
    event_id: uuid.UUID
    event_type: ReplanningEventType
    request_id: uuid.UUID | None
    engineer_id: uuid.UUID | None
    occurred_at: datetime
    plan: EventPlanSummaryResponse

    @field_validator("occurred_at")
    @classmethod
    def attach_utc(cls, value: datetime) -> datetime:
        return as_utc(value)
