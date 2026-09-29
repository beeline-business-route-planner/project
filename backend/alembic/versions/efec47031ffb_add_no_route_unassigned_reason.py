"""add no_route unassigned reason

Revision ID: efec47031ffb
Revises: 1fdcb8bfcf2b
Create Date: 2026-09-27 16:25:42.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "efec47031ffb"
down_revision: str | Sequence[str] | None = "1fdcb8bfcf2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Autogenerate не видит новые значения PostgreSQL ENUM, поэтому ALTER TYPE вручную."""
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE unassigned_reason ADD VALUE IF NOT EXISTS 'NO_ROUTE' AFTER 'NO_TIME_SLOT'"
        )


def downgrade() -> None:
    """Значение ENUM нельзя удалить без пересоздания типа и потери строк с этой причиной."""
    raise NotImplementedError("Downgrade would discard unassigned requests with NO_ROUTE")
