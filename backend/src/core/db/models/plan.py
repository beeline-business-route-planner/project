import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.enums import PlanKind, Region, plan_kind_enum, region_enum
from src.core.db.models.base import Base


class Plan(Base):
    """Версия плана распределения заявок по инженерам для одного округа.

    `based_on_plan_id` — явная ссылка на план, из которого получен этот (self-FK),
    чтобы диспетчеру можно было показать диф old/new именно относительно него, а не
    "последнего по времени" (может отличаться, если план строят не по цепочке).
    `upload_id` — с какой выгрузки данных посчитан план: для `manual_replan` это та же
    выгрузка, что и у предыдущего плана округа (новых файлов не было), для `initial` —
    свежая. `triggered_by_event_id` заполнен только у `event_replan`.
    `is_baseline` — план, посчитанный базовым алгоритмом (см. TECHNICAL_CONSTRAINTS.md,
    §5) для обязательного сравнения метрик, не результат оптимизации.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    region: Mapped[Region] = mapped_column(region_enum)
    upload_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("dataupload.id", ondelete="RESTRICT")
    )
    kind: Mapped[PlanKind] = mapped_column(plan_kind_enum)
    is_baseline: Mapped[bool] = mapped_column(sa.Boolean(), default=False)

    based_on_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("plan.id", ondelete="SET NULL")
    )
    triggered_by_event_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("replanningevent.id", ondelete="SET NULL")
    )

    total_mileage_km: Mapped[Decimal] = mapped_column(sa.Numeric(9, 2))
    engineers_used_count: Mapped[int] = mapped_column(sa.SmallInteger())

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())

    __table_args__ = (
        sa.CheckConstraint(
            "kind != 'EVENT_REPLAN' or triggered_by_event_id is not null",
            name="ck_plan_event_replan_has_event",
        ),
    )
