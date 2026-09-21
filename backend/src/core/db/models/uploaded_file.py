import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.models.base import Base


class UploadedFile(Base):
    """Оригинальный файл, загруженный диспетчером (хранится в S3), привязан к выгрузке.

    На одну `DataUpload` обычно приходится 2 файла (заявки + инженеры), поэтому связь
    "выгрузка → файлы" один-ко-многим, не один-к-одному.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid7
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("dataupload.id", ondelete="CASCADE"),
    )
    filename: Mapped[str] = mapped_column(sa.String(255))
    content_type: Mapped[str] = mapped_column(sa.String(255))
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger())
    s3_bucket: Mapped[str] = mapped_column(sa.String(255))
    s3_key: Mapped[str] = mapped_column(sa.String(1024), unique=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(), server_default=sa.func.now())
