import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.models.base import Base


class PlanStop(Base):
    """Одна остановка маршрута инженера в конкретном плане (назначенная заявка).

    Заявки, которых нет ни в одном `PlanStop` данного плана — неназначенные
    (см. TECHNICAL_CONSTRAINTS.md, §6); причина неназначения — забота сервисного
    слоя/вывода алгоритма, не хранится как колонка на этом этапе.

    `is_locked` — остановка перенесена из предыдущего плана без изменений, потому что
    её время начала уже в прошлом на момент перепланирования (см. кейс "manual_replan":
    уже стартовавшие/прошедшие точки не трогаем, дальше — пересчитываем).
    """

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("plan.id", ondelete="CASCADE")
    )
    engineer_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("engineer.id", ondelete="RESTRICT")
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("request.id", ondelete="RESTRICT")
    )

    sequence_number: Mapped[int] = mapped_column(sa.SmallInteger())
    planned_arrival: Mapped[datetime] = mapped_column(sa.DateTime())
    travel_minutes: Mapped[int] = mapped_column(sa.SmallInteger())
    distance_km: Mapped[Decimal] = mapped_column(sa.Numeric(6, 2))
    is_locked: Mapped[bool] = mapped_column(sa.Boolean(), default=False)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())

    __table_args__ = (
        sa.UniqueConstraint("plan_id", "engineer_id", "sequence_number", name="uq_plan_stop_order"),
        sa.UniqueConstraint("plan_id", "request_id", name="uq_plan_stop_request"),
    )
