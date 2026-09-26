import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.models.base import Base


class PlanEngineerState(Base):
    """Замороженная доступность инженера в конкретной версии плана."""

    plan_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("plan.id", ondelete="CASCADE"),
        primary_key=True,
    )
    engineer_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("engineer.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    is_available: Mapped[bool] = mapped_column(sa.Boolean())
