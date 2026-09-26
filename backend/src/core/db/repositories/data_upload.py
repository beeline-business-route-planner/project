import uuid

from src.core.db.enums import Region
from src.core.db.models import DataUpload
from src.core.db.repositories.base import BaseRepository


class DataUploadRepository(BaseRepository[DataUpload]):
    model = DataUpload

    def create(self, region: Region) -> uuid.UUID:
        upload_id = uuid.uuid7()
        upload = DataUpload()
        upload.id = upload_id
        upload.region = region
        self.add(upload)
        return upload_id
