import aioboto3
from aiobotocore.config import AioConfig
from aiobotocore.session import ClientCreatorContext
from types_aiobotocore_s3.client import S3Client as BotoS3Client

from src.config import cfg


class S3Client:
    """Тонкая обёртка над `aioboto3.Session` для подключения к S3-совместимому хранилищу.

    Сама `aioboto3.Session` не хранит соединение и безопасна для
    переиспользования между запросами — низкоуровневый клиент открывается
    отдельно на каждую операцию через `get()`.
    """

    def __init__(self, session: aioboto3.Session) -> None:
        self._session = session

    def get(self, *, public: bool = False) -> ClientCreatorContext[BotoS3Client]:
        return self._session.client(
            "s3",
            endpoint_url=(
                cfg.s3.public_endpoint_url or cfg.s3.endpoint_url if public else cfg.s3.endpoint_url
            ),
            aws_access_key_id=cfg.s3.access_key,
            aws_secret_access_key=cfg.s3.secret_key,
            region_name=cfg.s3.region,
            config=AioConfig(
                connect_timeout=cfg.s3.connect_timeout_seconds,
                read_timeout=cfg.s3.read_timeout_seconds,
            ),
        )
