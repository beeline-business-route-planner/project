import sqlalchemy as sa

from src.core.db.enums import (
    ApprovalStatus,
    ConnectionType,
    DistributionMode,
    PlanKind,
    PlanStrategy,
    Region,
    ReplanningEventType,
    RequestStatus,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    UnassignedReason,
    VehicleType,
)

# Общие postgres ENUM-типы создаются миграциями и переиспользуются ORM-моделями.
skill_enum = sa.Enum(Skill, name="skill")
vehicle_type_enum = sa.Enum(VehicleType, name="vehicle_type")
request_type_bk_enum = sa.Enum(RequestTypeBk, name="request_type_bk")
request_type_hd_enum = sa.Enum(RequestTypeHd, name="request_type_hd")
connection_type_enum = sa.Enum(ConnectionType, name="connection_type")
request_status_enum = sa.Enum(RequestStatus, name="request_status")
approval_status_enum = sa.Enum(ApprovalStatus, name="approval_status")
region_enum = sa.Enum(Region, name="region")
plan_kind_enum = sa.Enum(PlanKind, name="plan_kind")
replanning_event_type_enum = sa.Enum(ReplanningEventType, name="replanning_event_type")
unassigned_reason_enum = sa.Enum(UnassignedReason, name="unassigned_reason")
distribution_mode_enum = sa.Enum(DistributionMode, name="distribution_mode")
plan_strategy_enum = sa.Enum(PlanStrategy, name="plan_strategy")
