from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db.repositories import (
    DataUploadRepository,
    EngineerRepository,
    RequestRepository,
    UploadedFileRepository,
)


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.data_uploads = DataUploadRepository(session)
        self.engineers = EngineerRepository(session)
        self.requests = RequestRepository(session)
        self.uploaded_files = UploadedFileRepository(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
