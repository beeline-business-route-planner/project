import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.enums import Region
from src.core.db.models.base import Base
from src.core.db.types import region_enum


class DataUpload(Base):
    """Выгрузка данных диспетчером — одна запись на один округ за раз.

    Диспетчер может разом загрузить файлы по всем округам или только по одному —
    на бэке это всегда N независимых `DataUpload`, по одной на округ (см.
    TECHNICAL_CONSTRAINTS.md, §1: округа — независимые пулы, не пересекаются).
    "Текущая"/"предыдущая" выгрузка округа — не отдельный флаг, а первая и вторая
    по `created_at` среди строк с этим `region`.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    region: Mapped[Region] = mapped_column(region_enum)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())
