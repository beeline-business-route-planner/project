from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from beeline_backend.domain.errors import DomainError


class RequestStatus(StrEnum):
    NOT_SENT = "NOT_SENT"
    SENT = "SENT"
    EN_ROUTE = "EN_ROUTE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Priority(StrEnum):
    NORMAL = "normal"
    URGENT = "urgent"


class WorkCode(StrEnum):
    CONNECTION = "connection"
    EMERGENCY = "emergency"
    EQUIPMENT_ORDER = "equipment_order"
    LOCAL = "local"


ALLOWED_STATUS_TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.NOT_SENT: {RequestStatus.SENT, RequestStatus.CANCELLED},
    RequestStatus.SENT: {
        RequestStatus.EN_ROUTE,
        RequestStatus.OVERDUE,
        RequestStatus.CANCELLED,
    },
    RequestStatus.EN_ROUTE: {
        RequestStatus.IN_PROGRESS,
        RequestStatus.OVERDUE,
        RequestStatus.CANCELLED,
    },
    RequestStatus.IN_PROGRESS: {
        RequestStatus.COMPLETED,
        RequestStatus.OVERDUE,
        RequestStatus.CANCELLED,
    },
    RequestStatus.OVERDUE: {
        RequestStatus.EN_ROUTE,
        RequestStatus.IN_PROGRESS,
        RequestStatus.COMPLETED,
        RequestStatus.CANCELLED,
    },
    RequestStatus.COMPLETED: set(),
    RequestStatus.CANCELLED: set(),
}


def ensure_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainError(
            "naive_datetime",
            f"{field_name} must contain a timezone",
            {"field": field_name},
        )


def validate_status_transition(current: RequestStatus, target: RequestStatus) -> None:
    if target == current:
        return
    if target not in ALLOWED_STATUS_TRANSITIONS[current]:
        raise DomainError(
            "invalid_status_transition",
            f"Transition {current.value} -> {target.value} is not allowed",
            {"current": current.value, "target": target.value},
        )


@dataclass(frozen=True, slots=True)
class VisitWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        ensure_aware(self.start, "window_start")
        ensure_aware(self.end, "window_end")
        if self.end <= self.start:
            raise DomainError("invalid_window", "Window end must be after start")


@dataclass(frozen=True, slots=True)
class VisitTiming:
    arrival: datetime
    start: datetime
    finish: datetime


def calculate_visit(
    previous_finish: datetime,
    travel_seconds: int,
    window: VisitWindow,
    service_minutes: int,
    shift_end: datetime,
) -> VisitTiming:
    ensure_aware(previous_finish, "previous_finish")
    ensure_aware(shift_end, "shift_end")
    if travel_seconds < 0 or service_minutes < 0:
        raise DomainError("negative_duration", "Durations cannot be negative")
    arrival = previous_finish + timedelta(seconds=travel_seconds)
    start = max(arrival, window.start)
    finish = start + timedelta(minutes=service_minutes)
    if finish > window.end:
        raise DomainError(
            "outside_client_window",
            "Work does not fully fit in the client window",
            {"finish": finish.isoformat(), "window_end": window.end.isoformat()},
        )
    if finish > shift_end:
        raise DomainError(
            "outside_shift",
            "Work does not fully fit in the engineer shift",
            {"finish": finish.isoformat(), "shift_end": shift_end.isoformat()},
        )
    return VisitTiming(arrival=arrival, start=start, finish=finish)


@dataclass(frozen=True, slots=True)
class Assignment:
    request_id: UUID
    engineer_id: UUID
    position: int
    from_location_id: UUID
    location_id: UUID
    arrival_at: datetime
    start_at: datetime
    finish_at: datetime
    travel_seconds: int
    distance_meters: int
    explanation: str


@dataclass(frozen=True, slots=True)
class Unassigned:
    request_id: UUID
    reason_code: str
    explanation: str


@dataclass(frozen=True, slots=True)
class PlanCandidate:
    schema_version: str
    input_version: str
    assignments: tuple[Assignment, ...] = field(default_factory=tuple)
    unassigned: tuple[Unassigned, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

