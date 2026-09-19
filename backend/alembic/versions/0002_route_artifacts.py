"""Persist versioned route artifacts and immutable segment references.

Revision ID: 0002_route_artifacts
Revises: 0001_initial
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0002_route_artifacts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("route_legs") as batch:
        batch.add_column(sa.Column("route_cache_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_route_leg_cache", "route_cache", ["route_cache_id"], ["id"], ondelete="RESTRICT"
        )
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "plan_route_artifacts",
        sa.Column(
            "plan_id", sa.Uuid(), sa.ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "engineer_id",
            sa.Uuid(),
            sa.ForeignKey("engineers.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("detailed", json_type, nullable=False),
        sa.Column("overview", json_type, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("plan_route_artifacts")
    with op.batch_alter_table("route_legs") as batch:
        batch.drop_constraint("fk_route_leg_cache", type_="foreignkey")
        batch.drop_column("route_cache_id")
