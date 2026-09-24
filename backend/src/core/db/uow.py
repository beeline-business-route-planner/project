from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db.repositories import (
    BaselineResultRepository,
    DataUploadRepository,
    EngineerRepository,
    PlanEngineerStateRepository,
    PlanRepository,
    PlanStopRepository,
    PlanUnassignedRequestRepository,
    ReplanningEventRepository,
    RequestRepository,
    UploadedFileRepository,
)


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.data_uploads = DataUploadRepository(session)
        self.baseline_results = BaselineResultRepository(session)
        self.engineers = EngineerRepository(session)
        self.requests = RequestRepository(session)
        self.replanning_events = ReplanningEventRepository(session)
        self.uploaded_files = UploadedFileRepository(session)
        self.plans = PlanRepository(session)
        self.plan_engineer_states = PlanEngineerStateRepository(session)
        self.plan_stops = PlanStopRepository(session)
        self.plan_unassigned_requests = PlanUnassignedRequestRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
