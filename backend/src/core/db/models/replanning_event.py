import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.enums import (
    ApprovalStatus,
    Region,
    ReplanningEventType,
)
from src.core.db.models.base import Base
from src.core.db.types import approval_status_enum, region_enum, replanning_event_type_enum


class ReplanningEvent(Base):
    """Внештатное событие, инициирующее перепланирование (см. TECHNICAL_CONSTRAINTS.md, §2, 4).

    `request_id` — для `urgent_request` (новая срочная заявка, уже созданная как
    `Request` с `upload_id is None`) и для `request_cancelled` (какая заявка отменена).
    `engineer_id` — для `engineer_unavailable` (машина сломалась, инженеру стало плохо
    и т.п.). Ровно одно из двух заполнено в зависимости от `event_type`.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    region: Mapped[Region] = mapped_column(region_enum)
    planning_date: Mapped[date] = mapped_column(sa.Date())
    event_type: Mapped[ReplanningEventType] = mapped_column(replanning_event_type_enum)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        approval_status_enum, default=ApprovalStatus.PENDING
    )
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime())

    request_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("request.id", ondelete="RESTRICT")
    )
    engineer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("engineer.id", ondelete="RESTRICT")
    )

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())
    approved_at: Mapped[datetime | None] = mapped_column(sa.DateTime())
    rejected_at: Mapped[datetime | None] = mapped_column(sa.DateTime())

    __table_args__ = (
        sa.CheckConstraint(
            "(event_type IN ('URGENT_REQUEST', 'REQUEST_CANCELLED') "
            "AND request_id IS NOT NULL AND engineer_id IS NULL) "
            "OR (event_type IN ('ENGINEER_UNAVAILABLE', 'ENGINEER_AVAILABLE') "
            "AND engineer_id IS NOT NULL AND request_id IS NULL)",
            name="ck_replanning_event_target",
        ),
        sa.CheckConstraint(
            "(approval_status = 'PENDING' AND approved_at IS NULL AND rejected_at IS NULL) "
            "OR (approval_status = 'APPROVED' AND approved_at IS NOT NULL "
            "AND rejected_at IS NULL) "
            "OR (approval_status = 'REJECTED' AND rejected_at IS NOT NULL "
            "AND approved_at IS NULL)",
            name="ck_replanning_event_approval_timestamps",
        ),
        sa.Index(
            "uq_replanning_event_pending_region_date",
            "region",
            "planning_date",
            unique=True,
            postgresql_where=sa.text("approval_status = 'PENDING'"),
        ),
    )
