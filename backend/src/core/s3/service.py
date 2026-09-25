from botocore.exceptions import BotoCoreError, ClientError

from src.core.s3.client import S3Client
from src.core.s3.exc import S3UnavailableError


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

    async def presigned_download_url(self, bucket: str, key: str, expires_in: int) -> str:
        try:
            async with self._client.get() as client:
                return await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=expires_in,
                )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise S3UnavailableError("Не удалось создать ссылку на объект S3") from exc
