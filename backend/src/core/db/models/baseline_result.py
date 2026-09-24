import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.models.base import Base


class BaselineResult(Base):
    """Агрегаты контрольного алгоритма для одного initial-кандидата."""

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    initial_plan_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("plan.id", ondelete="CASCADE"),
        unique=True,
    )
    assigned_requests_count: Mapped[int] = mapped_column(sa.Integer())
    unassigned_requests_count: Mapped[int] = mapped_column(sa.Integer())
    engineers_used_count: Mapped[int] = mapped_column(sa.SmallInteger())
    total_mileage_km: Mapped[Decimal] = mapped_column(sa.Numeric(9, 2))
    average_workload_with_travel: Mapped[Decimal] = mapped_column(sa.Numeric(7, 2))
    average_workload_without_travel: Mapped[Decimal] = mapped_column(sa.Numeric(7, 2))
    algorithm_version: Mapped[str] = mapped_column(sa.String(100))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())
