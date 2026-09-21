import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.enums import Region, ReplanningEventType, region_enum, replanning_event_type_enum
from src.core.db.models.base import Base


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
    event_type: Mapped[ReplanningEventType] = mapped_column(replanning_event_type_enum)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime())

    request_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("request.id", ondelete="SET NULL")
    )
    engineer_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("engineer.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())

    __table_args__ = (
        sa.CheckConstraint(
            "request_id is not null or engineer_id is not null",
            name="ck_replanning_event_target",
        ),
    )
