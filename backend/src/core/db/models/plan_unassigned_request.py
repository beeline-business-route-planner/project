import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.enums import UnassignedReason
from src.core.db.models.base import Base
from src.core.db.types import unassigned_reason_enum


class PlanUnassignedRequest(Base):
    """Заявка, которую план не смог разместить ни у одного инженера, и причина.

    Зеркало `PlanStop` для отрицательного случая: причина замораживается в момент
    построения плана, а не пересчитывается по запросу — время в пути динамическое,
    и позже пересчёт мог бы дать другой ответ, чем реально был у алгоритма
    (см. TECHNICAL_CONSTRAINTS.md, §3: сервис обязан явно показать причину).
    """

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("plan.id", ondelete="CASCADE")
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("request.id", ondelete="RESTRICT")
    )
    reason: Mapped[UnassignedReason] = mapped_column(unassigned_reason_enum)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())

    __table_args__ = (
        sa.UniqueConstraint("plan_id", "request_id", name="uq_plan_unassigned_request"),
    )
