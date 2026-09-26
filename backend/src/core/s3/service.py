import re
import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse

from botocore.exceptions import BotoCoreError, ClientError

from src.config import cfg
from src.core.s3.client import S3Client
from src.core.s3.dto import ExportDownload
from src.core.s3.enums import ExportKind
from src.core.s3.exc import ExportTooLargeError, S3UnavailableError


class S3Storage:
    """Операции над объектами в бакете S3-совместимого хранилища (MinIO)."""

    def __init__(self, client: S3Client) -> None:
        self._client = client

    async def upload_file(
        self, bucket: str, key: str, data: bytes, content_type: str | None = None
    ) -> None:
        """Загружает файл в бакет.

        Args:
            bucket: имя бакета.
            key: путь/имя объекта внутри бакета.
            data: содержимое файла.
            content_type: MIME-тип файла, если известен.
        """
        try:
            async with self._client.get() as client:
                if content_type:
                    await client.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=data,
                        ContentType=content_type,
                    )
                else:
                    await client.put_object(Bucket=bucket, Key=key, Body=data)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise S3UnavailableError("Не удалось загрузить объект в S3") from exc

    async def download_file(self, bucket: str, key: str) -> bytes:
        """Скачивает файл из бакета целиком в память."""
        try:
            async with self._client.get() as client:
                response = await client.get_object(Bucket=bucket, Key=key)
                return await response["Body"].read()
        except (BotoCoreError, ClientError, OSError) as exc:
            raise S3UnavailableError("Не удалось скачать объект из S3") from exc

    async def delete_file(self, bucket: str, key: str) -> None:
        """Удаляет файл из бакета."""
        try:
            async with self._client.get() as client:
                await client.delete_object(Bucket=bucket, Key=key)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise S3UnavailableError("Не удалось удалить объект из S3") from exc

    async def presigned_download_url(
        self, bucket: str, key: str, expires_in: int, filename: str, content_type: str
    ) -> str:
        try:
            async with self._client.get(public=True) as client:
                url = await client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": bucket,
                        "Key": key,
                        "ResponseContentDisposition": f'attachment; filename="{filename}"',
                        "ResponseContentType": content_type,
                    },
                    ExpiresIn=expires_in,
                )
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise S3UnavailableError("S3 вернул некорректную ссылку")
                return url
        except (BotoCoreError, ClientError, OSError, ValueError, TypeError) as exc:
            raise S3UnavailableError("Не удалось создать ссылку на объект S3") from exc


class S3ExportDelivery:
    """Загружает готовые экспорты в отдельный бакет и выдаёт временную ссылку."""

    def __init__(self, storage: S3Storage) -> None:
        self._storage = storage

    async def deliver(
        self,
        *,
        data: bytes,
        kind: ExportKind,
        planning_date: date,
        filename: str,
        content_type: str,
    ) -> ExportDownload:
        if len(data) > cfg.s3.max_export_size_bytes:
            raise ExportTooLargeError
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", filename) or ".." in filename:
            raise ValueError("Некорректное имя экспортируемого файла")
        key = (
            f"{cfg.s3.export_prefix}/{kind.value}/{planning_date.isoformat()}/"
            f"{uuid.uuid4()}/{filename}"
        )
        expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(
            seconds=cfg.s3.export_url_ttl_seconds
        )
        url = await self._storage.presigned_download_url(
            cfg.s3.bucket_exports,
            key,
            cfg.s3.export_url_ttl_seconds,
            filename,
            content_type,
        )
        await self._storage.upload_file(cfg.s3.bucket_exports, key, data, content_type)
        return ExportDownload(
            url=url,
            expires_at=expires_at,
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
        )
