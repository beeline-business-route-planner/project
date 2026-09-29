"""add plan mode and strategy

Revision ID: 1e820cf38929
Revises: efec47031ffb
Create Date: 2026-09-27 16:30:08.944605

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1e820cf38929"
down_revision: str | Sequence[str] | None = "efec47031ffb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Режим и стратегия плана; существующие планы считались min_engineers + layered_graph."""
    bind = op.get_bind()
    distribution_mode = postgresql.ENUM("MIN_ENGINEERS", "BALANCED", name="distribution_mode")
    distribution_mode.create(bind, checkfirst=True)
    plan_strategy = postgresql.ENUM("LAYERED_GRAPH", "LNS", "GREEDY", name="plan_strategy")
    plan_strategy.create(bind, checkfirst=True)

    op.add_column(
        "plan",
        sa.Column(
            "mode",
            postgresql.ENUM(name="distribution_mode", create_type=False),
            nullable=False,
            server_default="MIN_ENGINEERS",
        ),
    )
    op.add_column(
        "plan",
        sa.Column(
            "strategy",
            postgresql.ENUM(name="plan_strategy", create_type=False),
            nullable=False,
            server_default="LAYERED_GRAPH",
        ),
    )
    op.alter_column("plan", "mode", server_default=None)
    op.alter_column("plan", "strategy", server_default=None)


def downgrade() -> None:
    """Откат потерял бы режим и стратегию, с которыми рассчитаны планы."""
    raise NotImplementedError("Downgrade would discard plan mode and strategy")
