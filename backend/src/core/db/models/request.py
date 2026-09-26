import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.enums import (
    ConnectionType,
    Region,
    RequestStatus,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    VehicleType,
)
from src.core.db.models.base import Base
from src.core.db.types import (
    connection_type_enum,
    region_enum,
    request_status_enum,
    request_type_bk_enum,
    request_type_hd_enum,
    skill_enum,
    vehicle_type_enum,
)


class Request(Base):
    """Заявка на выполнение работ инженером.

    Поля `type_bk`/`type_hd`/`district`/`connection_type`/`is_gigabit` — как они
    приходят из источника (Beekeeper/HelpDesk выгрузка); `norm_minutes`,
    `norm_minutes_without_travel`, `priority`, `required_skill`,
    `required_vehicle_type` — нормализованные поля, которые использует алгоритм
    распределения (см. TECHNICAL_CONSTRAINTS.md, §2-3).

    `norm_minutes` — полный норматив выполнения из "Нормативы.xlsx" (включает
    фиксированные ~20 мин на дорогу). `norm_minutes_without_travel` — тот же
    норматив за вычетом дорожной части: чистое время работы у клиента, которое
    используется вместе с расчётным временем маршрута вместо зашитой в таблицу
    константы (см. TECHNICAL_CONSTRAINTS.md, §2, "Нормативы длительности").

    `upload_id` — nullable: для срочной заявки, появившейся из события
    перепланирования (а не из файла выгрузки), выгрузки не будет.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), sa.ForeignKey("dataupload.id", ondelete="SET NULL")
    )
    external_id: Mapped[int] = mapped_column(sa.BigInteger())

    type_bk: Mapped[RequestTypeBk] = mapped_column(request_type_bk_enum)
    type_hd: Mapped[RequestTypeHd] = mapped_column(request_type_hd_enum)

    region: Mapped[Region] = mapped_column(region_enum)
    district: Mapped[str] = mapped_column(sa.String(255))
    address: Mapped[str] = mapped_column(sa.String(512))
    latitude: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 6))

    connection_type: Mapped[ConnectionType | None] = mapped_column(connection_type_enum)
    is_gigabit: Mapped[bool] = mapped_column(sa.Boolean())

    window_start: Mapped[datetime] = mapped_column(sa.DateTime())
    window_end: Mapped[datetime] = mapped_column(sa.DateTime())

    norm_minutes: Mapped[int] = mapped_column(sa.SmallInteger())
    norm_minutes_without_travel: Mapped[int] = mapped_column(sa.SmallInteger())

    priority: Mapped[int] = mapped_column(sa.SmallInteger())

    required_skill: Mapped[Skill] = mapped_column(skill_enum)
    required_vehicle_type: Mapped[VehicleType | None] = mapped_column(vehicle_type_enum)
    status: Mapped[RequestStatus] = mapped_column(
        request_status_enum, default=RequestStatus.NOT_SENT
    )

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.clock_timestamp()
    )

    __table_args__ = (
        sa.CheckConstraint("priority between 1 and 3", name="ck_request_priority"),
        sa.UniqueConstraint("upload_id", "external_id", name="uq_request_upload_external_id"),
    )
