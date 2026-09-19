"""Add idempotency keys to planning runs.

Revision ID: 0003_planning_idempotency
Revises: 0002_route_artifacts
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_planning_idempotency"
down_revision = "0002_route_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("planning_runs") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(255), nullable=True))
        batch.create_unique_constraint(
            "uq_planning_run_idempotency", ["idempotency_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("planning_runs") as batch:
        batch.drop_constraint("uq_planning_run_idempotency", type_="unique")
        batch.drop_column("idempotency_key")
