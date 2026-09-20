from src.core.s3.client import S3Client


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
        async with self._client.get() as client:
            if content_type:
                await client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
            else:
                await client.put_object(Bucket=bucket, Key=key, Body=data)

    async def download_file(self, bucket: str, key: str) -> bytes:
        """Скачивает файл из бакета целиком в память."""
        async with self._client.get() as client:
            response = await client.get_object(Bucket=bucket, Key=key)
            return await response["Body"].read()

    async def delete_file(self, bucket: str, key: str) -> None:
        """Удаляет файл из бакета."""
        async with self._client.get() as client:
            await client.delete_object(Bucket=bucket, Key=key)
