from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db.repositories import (
    DataUploadRepository,
    EngineerRepository,
    PlanRepository,
    PlanStopRepository,
    PlanUnassignedRequestRepository,
    RequestRepository,
    UploadedFileRepository,
)


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.data_uploads = DataUploadRepository(session)
        self.engineers = EngineerRepository(session)
        self.requests = RequestRepository(session)
        self.uploaded_files = UploadedFileRepository(session)
        self.plans = PlanRepository(session)
        self.plan_stops = PlanStopRepository(session)
        self.plan_unassigned_requests = PlanUnassignedRequestRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
