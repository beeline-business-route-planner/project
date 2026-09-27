import aioboto3
from dishka import Provider, Scope, provide

from src.core.s3 import S3Client, S3ExportDelivery, S3Storage


class S3Provider(Provider):
    @provide(scope=Scope.APP)
    def get_session(self) -> aioboto3.Session:
        return aioboto3.Session()

    @provide(scope=Scope.APP)
    def get_s3_client(self, session: aioboto3.Session) -> S3Client:
        return S3Client(session)

    @provide(scope=Scope.APP)
    def get_s3_storage(self, client: S3Client) -> S3Storage:
        return S3Storage(client)

    @provide(scope=Scope.APP)
    def get_s3_export_delivery(self, storage: S3Storage) -> S3ExportDelivery:
        return S3ExportDelivery(storage)
