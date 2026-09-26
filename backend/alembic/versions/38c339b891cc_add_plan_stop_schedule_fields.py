"""add_plan_stop_schedule_fields

Revision ID: 38c339b891cc
Revises: e74b6ef9de8d
Create Date: 2026-09-23 15:01:26.751327

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "38c339b891cc"
down_revision: str | Sequence[str] | None = "e74b6ef9de8d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("planstop", sa.Column("planned_start", sa.DateTime(), nullable=True))
    op.add_column("planstop", sa.Column("planned_finish", sa.DateTime(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE planstop AS stop
            SET
                planned_start = GREATEST(stop.planned_arrival, request.window_start),
                planned_finish = GREATEST(stop.planned_arrival, request.window_start)
                    + request.norm_minutes_without_travel * INTERVAL '1 minute'
            FROM request
            WHERE request.id = stop.request_id
            """
        )
    )
    op.alter_column("planstop", "planned_start", existing_type=sa.DateTime(), nullable=False)
    op.alter_column("planstop", "planned_finish", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Downgrade would irreversibly discard plan stop schedule fields")
