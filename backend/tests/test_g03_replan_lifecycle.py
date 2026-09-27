import unittest
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.api.exc.plans import (
    PlanBaseChangedError,
    PlanStateChangedError,
    PlanStopAlreadyStartedError,
)
from src.api.plans.service import PlanService
from src.core.db.enums import PlanKind, Region


class ReplanDecisionIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 25, 13)
        self.created_at = datetime(2026, 9, 25, 9)
        self.base_id = uuid.UUID(int=1)
        self.request_id = uuid.UUID(int=2)
        self.engineer_id = uuid.UUID(int=3)
        self.plan = SimpleNamespace(
            id=uuid.UUID(int=4),
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 25),
            kind=PlanKind.REPLAN,
            based_on_plan_id=self.base_id,
            calculation_cutoff_at=datetime(2026, 9, 25, 12),
            created_at=self.created_at,
        )
        self.locked_stop = SimpleNamespace(
            request_id=self.request_id,
            engineer_id=self.engineer_id,
            sequence_number=1,
            planned_arrival=self.now - timedelta(hours=2),
            planned_start=self.now - timedelta(hours=2),
            planned_finish=self.now - timedelta(hours=1),
            travel_minutes=5,
            distance_km=Decimal("1.00"),
            is_locked=True,
        )
        self.uow = SimpleNamespace(
            plans=SimpleNamespace(
                get_current=AsyncMock(return_value=SimpleNamespace(id=self.base_id))
            ),
            replanning_events=SimpleNamespace(list_approved_after=AsyncMock(return_value=[])),
            plan_stops=SimpleNamespace(get_by_plan_id=AsyncMock(return_value=[self.locked_stop])),
            plan_unassigned_requests=SimpleNamespace(get_by_plan_id=AsyncMock(return_value=[])),
            requests=SimpleNamespace(
                get_by_ids_for_update=AsyncMock(
                    return_value=[SimpleNamespace(id=self.request_id, updated_at=self.created_at)]
                )
            ),
            plan_engineer_states=SimpleNamespace(
                get_by_plan_id=AsyncMock(
                    return_value=[SimpleNamespace(engineer_id=self.engineer_id, is_available=True)]
                )
            ),
            engineers=SimpleNamespace(
                get_by_ids_for_update=AsyncMock(
                    return_value=[SimpleNamespace(id=self.engineer_id, is_available=True)]
                )
            ),
        )
        self.service = PlanService(self.uow)

    async def test_late_approval_accepts_identical_locked_history(self) -> None:
        await self.service._validate_approval(self.plan, self.now, self.created_at)

    async def test_new_current_rejects_old_candidate(self) -> None:
        self.uow.plans.get_current.return_value = SimpleNamespace(id=uuid.UUID(int=5))
        with self.assertRaises(PlanBaseChangedError):
            await self.service._validate_approval(self.plan, self.now, self.created_at)

    async def test_approved_event_after_cutoff_rejects_candidate(self) -> None:
        self.uow.replanning_events.list_approved_after.return_value = [object()]
        with self.assertRaises(PlanStateChangedError):
            await self.service._validate_approval(self.plan, self.now, self.created_at)

    async def test_changed_request_rejects_candidate(self) -> None:
        self.uow.requests.get_by_ids_for_update.return_value[0].updated_at = (
            self.created_at + timedelta(microseconds=1)
        )
        with self.assertRaises(PlanStateChangedError):
            await self.service._validate_approval(self.plan, self.now, self.created_at)

    async def test_removed_base_unassigned_request_is_still_checked(self) -> None:
        removed_id = uuid.UUID(int=5)
        self.uow.plan_unassigned_requests.get_by_plan_id.side_effect = [
            [],
            [SimpleNamespace(request_id=removed_id)],
        ]
        with self.assertRaises(PlanStateChangedError):
            await self.service._validate_approval(self.plan, self.now, self.created_at)
        self.uow.requests.get_by_ids_for_update.assert_awaited_once_with(
            {self.request_id, removed_id}
        )

    async def test_changed_engineer_availability_rejects_candidate(self) -> None:
        self.uow.engineers.get_by_ids_for_update.return_value[0].is_available = False
        with self.assertRaises(PlanStateChangedError):
            await self.service._validate_approval(self.plan, self.now, self.created_at)

    async def test_changed_past_stop_rejects_candidate(self) -> None:
        changed = SimpleNamespace(**vars(self.locked_stop))
        changed.planned_finish += timedelta(minutes=1)
        self.uow.plan_stops.get_by_plan_id.side_effect = [[changed], [self.locked_stop]]
        with self.assertRaises(PlanStopAlreadyStartedError):
            await self.service._validate_approval(self.plan, self.now, self.created_at)

    def test_waiting_stop_can_change_before_work_starts(self) -> None:
        base = self._waiting_stop()
        changed = SimpleNamespace(**vars(base))
        changed.planned_start += timedelta(minutes=10)
        changed.planned_finish += timedelta(minutes=10)
        changed.is_locked = False
        PlanService._validate_past_stops([changed], [base], self.now)

    def test_identical_departed_stop_can_be_approved_before_work_starts(self) -> None:
        base = self._waiting_stop()
        copied = SimpleNamespace(**vars(base))
        PlanService._validate_past_stops([copied], [base], self.now)

    def _waiting_stop(self) -> SimpleNamespace:
        return SimpleNamespace(
            request_id=self.request_id,
            engineer_id=self.engineer_id,
            sequence_number=1,
            planned_arrival=self.now - timedelta(minutes=10),
            planned_start=self.now + timedelta(minutes=15),
            planned_finish=self.now + timedelta(hours=1),
            travel_minutes=20,
            distance_km=Decimal("5.00"),
            is_locked=True,
        )
