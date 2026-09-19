"""Persist assignment reason codes and planner violations.

Revision ID: 0004_plan_explanations
Revises: 0003_planning_idempotency
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0004_plan_explanations"
down_revision = "0003_planning_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    with op.batch_alter_table("assignments") as batch:
        batch.add_column(
            sa.Column("reason_codes", json_type, nullable=False, server_default="[]")
        )
    op.create_table(
        "plan_violations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "request_id",
            sa.Uuid(),
            sa.ForeignKey("requests.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("violation_type", sa.String(128), nullable=False),
        sa.Column("details", json_type, nullable=False),
    )
    op.create_index("ix_plan_violation_plan", "plan_violations", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_violation_plan", table_name="plan_violations")
    op.drop_table("plan_violations")
    with op.batch_alter_table("assignments") as batch:
        batch.drop_column("reason_codes")
