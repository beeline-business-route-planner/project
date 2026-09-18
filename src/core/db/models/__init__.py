from src.core.db.models.base import Base

# Alembic's env.py imports Base from this package (not from .base directly).
# Every new model module must be imported here so it registers on Base.metadata
# and alembic autogenerate picks it up, e.g.:
# from src.core.db.models.user import User

__all__ = [
    "Base",
]
