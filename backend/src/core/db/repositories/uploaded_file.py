from src.core.db.dto import UploadedFileCreateDTO
from src.core.db.models import UploadedFile
from src.core.db.repositories.base import BaseRepository


class UploadedFileRepository(BaseRepository[UploadedFile]):
    model = UploadedFile

    def add_many(self, files: list[UploadedFileCreateDTO]) -> None:
        for file in files:
            uploaded_file = UploadedFile()
            uploaded_file.upload_id = file.upload_id
            uploaded_file.filename = file.filename
            uploaded_file.content_type = file.content_type
            uploaded_file.size_bytes = file.size_bytes
            uploaded_file.s3_bucket = file.s3_bucket
            uploaded_file.s3_key = file.s3_key
            self.add(uploaded_file)
