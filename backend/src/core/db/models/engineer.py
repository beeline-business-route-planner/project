import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.db.enums import Region, VehicleType
from src.core.db.models.base import Base
from src.core.db.models.engineer_skill import EngineerSkill
from src.core.db.types import region_enum, vehicle_type_enum


class Engineer(Base):
    """Инженер (в данных — "бригада"), выполняющий заявки одного округа."""

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("dataupload.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(sa.String(255))

    region: Mapped[Region] = mapped_column(region_enum)
    start_point_address: Mapped[str] = mapped_column(sa.String(512))
    start_point_latitude: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 6))
    start_point_longitude: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 6))

    shift_start: Mapped[datetime] = mapped_column(sa.DateTime())
    shift_end: Mapped[datetime] = mapped_column(sa.DateTime())

    skills: Mapped[list[EngineerSkill]] = relationship(cascade="all, delete-orphan")
    vehicle_type: Mapped[VehicleType] = mapped_column(vehicle_type_enum)
    is_available: Mapped[bool] = mapped_column(sa.Boolean(), default=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()
    )
