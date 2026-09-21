import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.enums import Skill, skill_enum
from src.core.db.models.base import Base


class EngineerSkill(Base):
    """Связь "инженер — навык" (многие-ко-многим).

    Инженер имеет от 1 до 3 навыков (см. TECHNICAL_CONSTRAINTS.md, §1) — это
    ограничение по количеству строк на инженера проверяется в сервисном слое при
    создании/обновлении инженера, а не CHECK-constraint'ом (postgres не умеет
    считать строки-соседи по FK в обычном CHECK без триггера).
    """

    engineer_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("engineer.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill: Mapped[Skill] = mapped_column(skill_enum, primary_key=True)
