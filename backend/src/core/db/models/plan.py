import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.enums import (
    ApprovalStatus,
    DistributionMode,
    PlanKind,
    PlanStrategy,
    Region,
)
from src.core.db.models.base import Base
from src.core.db.types import (
    approval_status_enum,
    distribution_mode_enum,
    plan_kind_enum,
    plan_strategy_enum,
    region_enum,
)


class Plan(Base):
    """Версия плана распределения заявок по инженерам для одного округа.

    `based_on_plan_id` — явная ссылка на план, из которого получен этот (self-FK),
    чтобы диспетчеру можно было показать диф old/new именно относительно него, а не
    "последнего по времени" (может отличаться, если план строят не по цепочке).
    `upload_id` — с какой выгрузки данных посчитан план: для `replan` это та же
    выгрузка, что и у предыдущего плана округа (новых файлов не было), для `initial` —
    свежая. `triggered_by_event_id` заполнен только у `event_replan`.
    `mode` и `strategy` — с какими режимом и стратегией рассчитан план; replan по
    умолчанию наследует их от плана, на котором основан.
    Baseline хранится отдельно в `BaselineResult` и не участвует в lifecycle планов.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    region: Mapped[Region] = mapped_column(region_enum)
    planning_date: Mapped[date] = mapped_column(sa.Date())
    upload_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("dataupload.id", ondelete="RESTRICT")
    )
    kind: Mapped[PlanKind] = mapped_column(plan_kind_enum)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        approval_status_enum, default=ApprovalStatus.PENDING
    )

    based_on_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("plan.id", ondelete="RESTRICT")
    )
    triggered_by_event_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("replanningevent.id", ondelete="RESTRICT"),
        unique=True,
    )
    calculation_cutoff_at: Mapped[datetime] = mapped_column(sa.DateTime())
    mode: Mapped[DistributionMode] = mapped_column(distribution_mode_enum)
    strategy: Mapped[PlanStrategy] = mapped_column(plan_strategy_enum)

    total_mileage_km: Mapped[Decimal] = mapped_column(sa.Numeric(9, 2))
    engineers_used_count: Mapped[int] = mapped_column(sa.SmallInteger())
    assigned_requests_count: Mapped[int] = mapped_column(sa.Integer())
    unassigned_requests_count: Mapped[int] = mapped_column(sa.Integer())

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())
    approved_at: Mapped[datetime | None] = mapped_column(sa.DateTime())
    rejected_at: Mapped[datetime | None] = mapped_column(sa.DateTime())

    __table_args__ = (
        sa.CheckConstraint(
            "(kind = 'INITIAL' AND based_on_plan_id IS NULL AND triggered_by_event_id IS NULL) "
            "OR (kind = 'REPLAN' AND based_on_plan_id IS NOT NULL "
            "AND triggered_by_event_id IS NULL) "
            "OR (kind = 'EVENT_REPLAN' AND based_on_plan_id IS NOT NULL "
            "AND triggered_by_event_id IS NOT NULL)",
            name="ck_plan_kind_links",
        ),
        sa.CheckConstraint(
            "(approval_status = 'PENDING' AND approved_at IS NULL AND rejected_at IS NULL) "
            "OR (approval_status = 'APPROVED' AND approved_at IS NOT NULL "
            "AND rejected_at IS NULL) "
            "OR (approval_status = 'REJECTED' AND rejected_at IS NOT NULL "
            "AND approved_at IS NULL)",
            name="ck_plan_approval_timestamps",
        ),
    )
