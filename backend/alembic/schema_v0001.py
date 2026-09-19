from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class ScenarioRow(Base):
    __tablename__ = "scenarios"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    office_location_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LocationRow(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("normalized_address", "region", name="uq_location_address_region"),
        CheckConstraint("latitude IS NULL OR (latitude >= -90 AND latitude <= 90)", name="ck_latitude"),
        CheckConstraint("longitude IS NULL OR (longitude >= -180 AND longitude <= 180)", name="ck_longitude"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    address: Mapped[str] = mapped_column(Text)
    normalized_address: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(String(160), default="Москва")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    coordinate_source: Mapped[str | None] = mapped_column(String(64))
    coordinate_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DatasetRow(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("scenario_id", "sha256", name="uq_dataset_scenario_hash"),
        Index("ix_dataset_scenario_date", "scenario_id", "planning_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scenario_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("scenarios.id", ondelete="RESTRICT")
    )
    planning_date: Mapped[date] = mapped_column(Date)
    source_name: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="accepted")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    raw_metadata: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, default=dict)


class ImportErrorRow(Base):
    __tablename__ = "import_errors"
    __table_args__ = (Index("ix_import_errors_dataset", "dataset_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="CASCADE")
    )
    file_name: Mapped[str] = mapped_column(String(255))
    sheet_name: Mapped[str] = mapped_column(String(255))
    row_number: Mapped[int | None] = mapped_column(Integer)
    field_name: Mapped[str | None] = mapped_column(String(255))
    reason_code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)


class WorkTypeRow(Base):
    __tablename__ = "work_types"
    __table_args__ = (
        CheckConstraint("service_minutes >= 0", name="ck_work_type_service_minutes"),
        CheckConstraint("full_normative_minutes >= 0", name="ck_work_type_full_minutes"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    service_minutes: Mapped[int] = mapped_column(Integer)
    full_normative_minutes: Mapped[int] = mapped_column(Integer)
    required_skill_code: Mapped[str] = mapped_column(String(64))


class SkillRow(Base):
    __tablename__ = "skills"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)


class TransportTypeRow(Base):
    __tablename__ = "transport_types"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    routing_profile: Mapped[str] = mapped_column(String(64), default="driving")


class RequestRow(Base):
    __tablename__ = "requests"
    __table_args__ = (
        UniqueConstraint("dataset_id", "external_id", name="uq_request_dataset_external"),
        CheckConstraint("window_end > window_start", name="ck_request_window"),
        CheckConstraint(
            "service_minutes IS NULL OR service_minutes >= 0", name="ck_request_service_minutes"
        ),
        Index("ix_request_scenario_date", "scenario_id", "planning_date"),
        Index("ix_request_location", "location_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scenario_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("scenarios.id", ondelete="RESTRICT")
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="RESTRICT")
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT")
    )
    external_id: Mapped[str] = mapped_column(String(128))
    planning_date: Mapped[date] = mapped_column(Date)
    bk_type: Mapped[str] = mapped_column(String(255))
    hd_type: Mapped[str] = mapped_column(String(255))
    district: Mapped[str] = mapped_column(String(255))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    work_type_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("work_types.id", ondelete="RESTRICT")
    )
    service_minutes: Mapped[int | None] = mapped_column(Integer)
    full_normative_minutes: Mapped[int | None] = mapped_column(Integer)
    required_skill_code: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("skills.code", ondelete="RESTRICT")
    )
    required_transport_code: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("transport_types.code", ondelete="RESTRICT")
    )
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    mapping_state: Mapped[str] = mapped_column(String(32), default="mapped")
    gigabit: Mapped[bool] = mapped_column(Boolean, default=False)
    connection_kind: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EngineerRow(Base):
    __tablename__ = "engineers"
    __table_args__ = (
        UniqueConstraint("scenario_id", "external_code", name="uq_engineer_scenario_code"),
        Index("ix_engineer_scenario", "scenario_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scenario_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("scenarios.id", ondelete="RESTRICT")
    )
    external_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    transport_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("transport_types.code", ondelete="RESTRICT")
    )
    home_location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT")
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EngineerSkillRow(Base):
    __tablename__ = "engineer_skills"
    engineer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("engineers.id", ondelete="CASCADE"), primary_key=True
    )
    skill_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("skills.code", ondelete="RESTRICT"), primary_key=True
    )


class ShiftRow(Base):
    __tablename__ = "shifts"
    __table_args__ = (
        UniqueConstraint("engineer_id", "shift_date", name="uq_shift_engineer_date"),
        CheckConstraint("end_time > start_time", name="ck_shift_time"),
        Index("ix_shift_date", "shift_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    engineer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("engineers.id", ondelete="CASCADE")
    )
    shift_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    available: Mapped[bool] = mapped_column(Boolean, default=True)


class RequestStatusEventRow(Base):
    __tablename__ = "request_status_events"
    __table_args__ = (
        Index("ix_status_event_request_recorded", "request_id", "recorded_at"),
        UniqueConstraint("idempotency_key", name="uq_status_event_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("requests.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(160))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_finish: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    corrects_event_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("request_status_events.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255))


class DayEventRow(Base):
    __tablename__ = "day_events"
    __table_args__ = (
        UniqueConstraint("scenario_id", "idempotency_key", name="uq_day_event_idempotency"),
        Index("ix_day_event_scenario_date", "scenario_id", "planning_date", "effective_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scenario_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("scenarios.id", ondelete="RESTRICT")
    )
    planning_date: Mapped[date] = mapped_column(Date)
    event_type: Mapped[str] = mapped_column(String(64))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(160))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, object]] = mapped_column(JSON_TYPE)
    processing_state: Mapped[str] = mapped_column(String(32), default="queued")


class PlanningRunRow(Base):
    __tablename__ = "planning_runs"
    __table_args__ = (Index("ix_run_scenario_date", "scenario_id", "planning_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scenario_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("scenarios.id", ondelete="RESTRICT")
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="RESTRICT")
    )
    planning_date: Mapped[date] = mapped_column(Date)
    base_plan_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "plans.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_planning_runs_base_plan",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32))
    algorithm: Mapped[str] = mapped_column(String(128))
    input_version: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_message: Mapped[str | None] = mapped_column(Text)
    diagnostics: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, default=dict)


class PlanRow(Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("scenario_id", "planning_date", "approved_slot", name="uq_active_plan"),
        Index("ix_plan_scenario_date", "scenario_id", "planning_date", "created_at"),
        Index("ix_plan_parent", "parent_plan_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scenario_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("scenarios.id", ondelete="RESTRICT")
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="RESTRICT")
    )
    planning_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("planning_runs.id", ondelete="RESTRICT"), unique=True
    )
    planning_date: Mapped[date] = mapped_column(Date)
    parent_plan_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="SET NULL")
    )
    base_plan_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), default="draft")
    approved_slot: Mapped[bool | None] = mapped_column(Boolean)
    schema_version: Mapped[str] = mapped_column(String(32))
    input_version: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE)
    warnings: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssignmentRow(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("plan_id", "request_id", name="uq_assignment_plan_request"),
        UniqueConstraint("plan_id", "engineer_id", "position", name="uq_assignment_position"),
        CheckConstraint("position > 0", name="ck_assignment_position"),
        CheckConstraint("finish_at >= start_at", name="ck_assignment_times"),
        CheckConstraint("travel_seconds >= 0", name="ck_assignment_travel"),
        CheckConstraint("distance_meters >= 0", name="ck_assignment_distance"),
        Index("ix_assignment_plan_engineer", "plan_id", "engineer_id", "position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="CASCADE"))
    request_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("requests.id", ondelete="RESTRICT")
    )
    engineer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("engineers.id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(Integer)
    from_location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT")
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT")
    )
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finish_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    travel_seconds: Mapped[int] = mapped_column(Integer)
    distance_meters: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text)


class UnassignedRequestRow(Base):
    __tablename__ = "unassigned_requests"
    __table_args__ = (UniqueConstraint("plan_id", "request_id", name="uq_unassigned_plan_request"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="CASCADE"))
    request_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("requests.id", ondelete="RESTRICT")
    )
    reason_code: Mapped[str] = mapped_column(String(128))
    explanation: Mapped[str] = mapped_column(Text)


class RouteLegRow(Base):
    __tablename__ = "route_legs"
    __table_args__ = (
        UniqueConstraint("plan_id", "engineer_id", "sequence", name="uq_route_leg_sequence"),
        CheckConstraint("duration_seconds >= 0", name="ck_route_leg_duration"),
        CheckConstraint("distance_meters >= 0", name="ck_route_leg_distance"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="CASCADE"))
    engineer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("engineers.id", ondelete="RESTRICT")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    from_location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT")
    )
    to_location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT")
    )
    duration_seconds: Mapped[int] = mapped_column(Integer)
    distance_meters: Mapped[int] = mapped_column(Integer)
    matrix_snapshot_key: Mapped[str] = mapped_column(String(128))
    geometry: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)


class PlanMetricRow(Base):
    __tablename__ = "plan_metrics"
    __table_args__ = (UniqueConstraint("plan_id", "metric_code", name="uq_plan_metric"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="CASCADE"))
    metric_code: Mapped[str] = mapped_column(String(128))
    numeric_value: Mapped[float | None] = mapped_column(Float)
    text_value: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32))


class PlanApprovalRow(Base):
    __tablename__ = "plan_approvals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="RESTRICT"), unique=True)
    actor: Mapped[str] = mapped_column(String(160))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    base_plan_id: Mapped[UUID | None] = mapped_column(Uuid)


class AuditLogRow(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_scenario_recorded", "scenario_id", "recorded_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scenario_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("scenarios.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(128))
    actor: Mapped[str] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(64))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    object_type: Mapped[str] = mapped_column(String(64))
    object_id: Mapped[str] = mapped_column(String(128))
    object_version: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, default=dict)


class GeocodeCacheRow(Base):
    __tablename__ = "geocode_cache"
    __table_args__ = (
        UniqueConstraint(
            "normalized_address", "region", "provider", "normalization_version", name="uq_geocode_key"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    normalized_address: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(64))
    normalization_version: Mapped[str] = mapped_column(String(32))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_payload: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, default=dict)


class RouteCacheRow(Base):
    __tablename__ = "route_cache"
    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_route_cache_key"),
        Index("ix_route_cache_provider", "provider", "profile"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    cache_key: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(64))
    provider_version: Mapped[str] = mapped_column(String(128))
    profile: Mapped[str] = mapped_column(String(64))
    time_bucket: Mapped[str | None] = mapped_column(String(64))
    origin: Mapped[dict[str, float]] = mapped_column(JSON_TYPE)
    destination: Mapped[dict[str, float]] = mapped_column(JSON_TYPE)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    distance_meters: Mapped[int | None] = mapped_column(Integer)
    geometry: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReportRow(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("plan_id", "format", "report_version", name="uq_report_version"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="RESTRICT"))
    format: Mapped[str] = mapped_column(String(16))
    report_version: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, default=dict)


class OutboxJobRow(Base):
    __tablename__ = "outbox_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_idempotency"),
        Index("ix_outbox_status_available", "status", "available_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, object]] = mapped_column(JSON_TYPE)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
