"""add manual plan provenance

Revision ID: a40ef2d0bab5
Revises: 1e820cf38929
Create Date: 2026-09-29 22:00:24.721973

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a40ef2d0bab5"
down_revision: str | Sequence[str] | None = "1e820cf38929"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет происхождение ручной версии и разрешает ревизии событий."""
    op.execute("ALTER TYPE plan_strategy ADD VALUE IF NOT EXISTS 'MANUAL'")
    op.execute("ALTER TYPE unassigned_reason ADD VALUE IF NOT EXISTS 'MANUAL_DECISION'")
    op.add_column("plan", sa.Column("edited_from_plan_id", sa.UUID(), nullable=True))
    op.drop_constraint("uq_plan_triggered_by_event_id", "plan", type_="unique")
    op.create_foreign_key(
        "fk_plan_edited_from_plan_id_plan",
        "plan",
        "plan",
        ["edited_from_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_plan_edited_from_other", "plan", "edited_from_plan_id IS NULL OR edited_from_plan_id <> id"
    )


def downgrade() -> None:
    """Откат потребовал бы удаления значений PostgreSQL enum и ручных планов."""
    raise NotImplementedError("Downgrade would discard manual plans")
