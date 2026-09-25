"""Normalize pre-G02 initial plan timestamps and baseline workloads.

Revision ID: 1fdcb8bfcf2b
Revises: 7f3b91c4a2de
Create Date: 2026-09-25 16:55:14.173694

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1fdcb8bfcf2b"
down_revision: str | Sequence[str] | None = "7f3b91c4a2de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """T03 wrote initial created_at in Moscow time and workloads as fractions.

    Only T03 plans have a BaselineResult. Older migrated plans were created by
    PostgreSQL and must retain their existing UTC timestamps. Decision times
    and calculation_cutoff_at already use their intended time conventions.
    """
    op.execute(
        sa.text(
            """
            UPDATE plan AS p
            SET created_at = (p.created_at AT TIME ZONE 'Europe/Moscow') AT TIME ZONE 'UTC'
            WHERE p.kind = 'INITIAL'
              AND EXISTS (
                  SELECT 1 FROM baselineresult AS b WHERE b.initial_plan_id = p.id
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE baselineresult
            SET average_workload_with_travel = average_workload_with_travel * 100,
                average_workload_without_travel = average_workload_without_travel * 100
            """
        )
    )


def downgrade() -> None:
    """Keep normalized values; reversing them could alter post-G02 plans."""
