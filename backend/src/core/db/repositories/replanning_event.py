import uuid
from datetime import date, datetime

from sqlalchemy import select

from src.core.db.dto import ReplanningEventCreateDTO
from src.core.db.enums import ApprovalStatus, Region, ReplanningEventType
from src.core.db.models import ReplanningEvent
from src.core.db.repositories.base import BaseRepository


class ReplanningEventRepository(BaseRepository[ReplanningEvent]):
    model = ReplanningEvent

    async def get_by_request_id(self, request_id: uuid.UUID) -> ReplanningEvent | None:
        result = await self._session.scalars(
            select(ReplanningEvent).where(ReplanningEvent.request_id == request_id).limit(1)
        )
        return result.first()

    async def get_pending(self, region: Region, planning_date: date) -> ReplanningEvent | None:
        result = await self._session.scalars(
            select(ReplanningEvent)
            .where(
                ReplanningEvent.region == region,
                ReplanningEvent.planning_date == planning_date,
                ReplanningEvent.approval_status == ApprovalStatus.PENDING,
            )
            .limit(1)
        )
        return result.first()

    async def get_latest_approved_for_engineer(
        self, engineer_id: uuid.UUID, planning_date: date
    ) -> ReplanningEvent | None:
        result = await self._session.scalars(
            select(ReplanningEvent)
            .where(
                ReplanningEvent.engineer_id == engineer_id,
                ReplanningEvent.planning_date == planning_date,
                ReplanningEvent.approval_status == ApprovalStatus.APPROVED,
                ReplanningEvent.event_type.in_(
                    (
                        ReplanningEventType.ENGINEER_UNAVAILABLE,
                        ReplanningEventType.ENGINEER_AVAILABLE,
                    )
                ),
            )
            .order_by(ReplanningEvent.approved_at.desc(), ReplanningEvent.id.desc())
            .limit(1)
        )
        return result.first()

    async def list_approved_after(
        self, region: Region, planning_date: date, cutoff: datetime
    ) -> list[ReplanningEvent]:
        result = await self._session.scalars(
            select(ReplanningEvent)
            .where(
                ReplanningEvent.region == region,
                ReplanningEvent.planning_date == planning_date,
                ReplanningEvent.approval_status == ApprovalStatus.APPROVED,
                ReplanningEvent.approved_at > cutoff,
            )
            .order_by(ReplanningEvent.approved_at, ReplanningEvent.id)
        )
        return list(result.all())

    async def has_approved_request_event(
        self, request_id: uuid.UUID, event_type: ReplanningEventType
    ) -> bool:
        result = await self._session.scalar(
            select(ReplanningEvent.id)
            .where(
                ReplanningEvent.request_id == request_id,
                ReplanningEvent.event_type == event_type,
                ReplanningEvent.approval_status == ApprovalStatus.APPROVED,
            )
            .limit(1)
        )
        return result is not None

    @staticmethod
    def set_approval_status(
        event: ReplanningEvent, status: ApprovalStatus, decided_at: datetime | None
    ) -> None:
        event.approval_status = status
        event.approved_at = decided_at if status == ApprovalStatus.APPROVED else None
        event.rejected_at = decided_at if status == ApprovalStatus.REJECTED else None

    def create(self, event: ReplanningEventCreateDTO) -> uuid.UUID:
        event_id = uuid.uuid7()
        model = ReplanningEvent()
        model.id = event_id
        model.region = event.region
        model.planning_date = event.planning_date
        model.event_type = event.event_type
        model.approval_status = ApprovalStatus.PENDING
        model.request_id = event.request_id
        model.engineer_id = event.engineer_id
        model.occurred_at = event.occurred_at
        self.add(model)
        return event_id
