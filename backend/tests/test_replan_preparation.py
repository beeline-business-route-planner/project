import unittest
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.api.exc.planning import PlanningCurrentPlanMissing
from src.api.planning.service import PlanningService
from src.core.db.enums import (
    ApprovalStatus,
    PlanKind,
    Region,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    UnassignedReason,
    VehicleType,
)
from src.core.db.models import (
    Engineer,
    EngineerSkill,
    Plan,
    PlanEngineerState,
    PlanStop,
    PlanUnassignedRequest,
    Request,
)


class ReplanPreparationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cutoff = datetime(2026, 9, 23, 12)
        self.plan = Plan(
            id=uuid.UUID(int=1),
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 23),
            upload_id=uuid.UUID(int=2),
            kind=PlanKind.INITIAL,
            approval_status=ApprovalStatus.APPROVED,
        )
        self.request = Request(
            id=uuid.UUID(int=3),
            upload_id=self.plan.upload_id,
            external_id=3,
            type_bk=RequestTypeBk.CONNECTION,
            type_hd=RequestTypeHd.CONNECTION_REQUEST,
            region=Region.VOSTOK,
            district="Район",
            address="Адрес",
            latitude=Decimal("55.750000"),
            longitude=Decimal("37.610000"),
            connection_type=None,
            is_gigabit=False,
            window_start=self.cutoff,
            window_end=self.cutoff + timedelta(hours=2),
            norm_minutes=80,
            norm_minutes_without_travel=60,
            priority=2,
            required_skill=Skill.CONNECTION_AND_ORDERS,
            required_vehicle_type=None,
            created_at=self.cutoff,
        )
        self.engineer = Engineer(
            id=uuid.UUID(int=4),
            upload_id=self.plan.upload_id,
            name="Анна",
            region=Region.VOSTOK,
            start_point_address="Офис",
            start_point_latitude=Decimal("55.750000"),
            start_point_longitude=Decimal("37.610000"),
            shift_start=self.cutoff - timedelta(hours=3),
            shift_end=self.cutoff + timedelta(hours=5),
            skills=[EngineerSkill(skill=Skill.CONNECTION_AND_ORDERS)],
            vehicle_type=VehicleType.CAR,
            is_available=True,
            created_at=self.cutoff,
        )
        self.stop = PlanStop(
            plan_id=self.plan.id,
            engineer_id=self.engineer.id,
            request_id=self.request.id,
            sequence_number=1,
            planned_arrival=self.cutoff,
            planned_start=self.cutoff,
            planned_finish=self.cutoff + timedelta(hours=1),
            travel_minutes=10,
            distance_km=Decimal("4.25"),
            is_locked=False,
        )
        self.uow = SimpleNamespace(
            plans=SimpleNamespace(
                get_current=AsyncMock(return_value=self.plan),
                get_approved_initial_cutoff=AsyncMock(return_value=datetime(2026, 9, 23, 9, 30)),
            ),
            plan_stops=SimpleNamespace(get_by_plan_id=AsyncMock(return_value=[self.stop])),
            plan_unassigned_requests=SimpleNamespace(get_by_plan_id=AsyncMock(return_value=[])),
            plan_engineer_states=SimpleNamespace(
                get_by_plan_id=AsyncMock(
                    return_value=[
                        PlanEngineerState(
                            plan_id=self.plan.id,
                            engineer_id=self.engineer.id,
                            is_available=True,
                        )
                    ]
                )
            ),
            requests=SimpleNamespace(get_by_ids=AsyncMock(return_value=[self.request])),
            engineers=SimpleNamespace(get_by_ids=AsyncMock(return_value=[self.engineer])),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        self.service = PlanningService(self.uow, None, None, None, None)

    async def test_approved_base_and_full_input_are_frozen_without_writes(self) -> None:
        snapshot = await self.service.prepare_replan_base(Region.VOSTOK, self.cutoff)

        self.assertEqual(snapshot.base_plan_id, self.plan.id)
        self.assertEqual(snapshot.upload_id, self.plan.upload_id)
        self.assertEqual(snapshot.calculation_cutoff_at, self.cutoff)
        self.assertEqual(snapshot.initial_cutoff_at, datetime(2026, 9, 23, 9, 30))
        self.assertEqual(snapshot.requests[0].id, self.request.id)
        self.assertEqual(snapshot.engineers[0].id, self.engineer.id)
        self.assertEqual(snapshot.stops[0].planned_start, self.stop.planned_start)
        self.assertEqual(snapshot.engineer_states[0].is_available, True)
        self.uow.plans.get_current.assert_awaited_once_with(Region.VOSTOK, self.cutoff.date())
        self.uow.commit.assert_not_awaited()
        self.uow.rollback.assert_not_awaited()

    async def test_missing_current_is_region_conflict(self) -> None:
        self.uow.plans.get_current.return_value = None
        with self.assertRaises(PlanningCurrentPlanMissing):
            await self.service.prepare_replan_base(Region.VOSTOK, self.cutoff)
        self.uow.plan_stops.get_by_plan_id.assert_not_awaited()

    async def test_missing_initial_is_region_conflict(self) -> None:
        self.uow.plans.get_approved_initial_cutoff.return_value = None
        with self.assertRaises(PlanningCurrentPlanMissing):
            await self.service.prepare_replan_base(Region.VOSTOK, self.cutoff)

    async def test_missing_plan_member_is_not_silently_dropped(self) -> None:
        self.uow.requests.get_by_ids.return_value = []
        with self.assertRaises(ValueError):
            await self.service.prepare_replan_base(Region.VOSTOK, self.cutoff)

    async def test_unassigned_requests_are_included(self) -> None:
        extra = Request(
            **{
                column.name: getattr(self.request, column.name)
                for column in Request.__table__.columns
                if column.name != "id"
            },
            id=uuid.UUID(int=5),
        )
        self.uow.plan_unassigned_requests.get_by_plan_id.return_value = [
            PlanUnassignedRequest(
                plan_id=self.plan.id,
                request_id=extra.id,
                reason=UnassignedReason.NO_TIME_SLOT,
            )
        ]
        self.uow.requests.get_by_ids.return_value = [self.request, extra]

        snapshot = await self.service.prepare_replan_base(Region.VOSTOK, self.cutoff)

        self.assertEqual({item.id for item in snapshot.requests}, {self.request.id, extra.id})
        self.assertEqual(snapshot.unassigned[0].request_id, extra.id)


if __name__ == "__main__":
    unittest.main()
