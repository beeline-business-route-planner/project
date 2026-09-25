import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from src.core.db.enums import ApprovalStatus, PlanKind, Region
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
