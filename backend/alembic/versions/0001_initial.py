"""Create normalized planning schema.

Revision ID: 0001_initial
Revises: None
"""
from pathlib import Path
from runpy import run_path

from alembic import op

# Frozen historical schema: never import the evolving application metadata here.
Base = run_path(str(Path(__file__).resolve().parents[1] / "schema_v0001.py"))["Base"]

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

