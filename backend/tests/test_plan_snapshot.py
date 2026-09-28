import unittest
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.api.plans.presenter import PlanPresenter
from src.api.plans.service import PlanService
from src.api.plans.snapshot import PlanSnapshotAssembler
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
    Plan,
    PlanEngineerState,
    PlanStop,
    PlanUnassignedRequest,
    Request,
)


class PlanSnapshotAssemblerTest(unittest.IsolatedAsyncioTestCase):
    def test_snapshot_keeps_unused_engineers_and_urgent_requests(self) -> None:
        upload_id = uuid.UUID(int=10)
        plan = Plan(
            id=uuid.UUID(int=1),
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 23),
            upload_id=upload_id,
            kind=PlanKind.EVENT_REPLAN,
            approval_status=ApprovalStatus.PENDING,
            based_on_plan_id=uuid.UUID(int=2),
            triggered_by_event_id=uuid.UUID(int=3),
            calculation_cutoff_at=datetime(2026, 9, 23, 12),
            total_mileage_km=Decimal("4.00"),
            engineers_used_count=1,
            assigned_requests_count=1,
            unassigned_requests_count=1,
            created_at=datetime(2026, 9, 23, 12),
            approved_at=None,
            rejected_at=None,
        )
        used = self._engineer(20, upload_id, "Анна")
        unused = self._engineer(21, upload_id, "Борис")
        imported = self._request(30, upload_id)
        urgent = self._request(31, None)
        stop = PlanStop(
            id=uuid.UUID(int=40),
            plan_id=plan.id,
            engineer_id=used.id,
            request_id=imported.id,
            sequence_number=1,
            planned_arrival=datetime(2026, 9, 23, 10),
            planned_start=datetime(2026, 9, 23, 10),
            planned_finish=datetime(2026, 9, 23, 11),
            travel_minutes=15,
            distance_km=Decimal("4.00"),
            is_locked=False,
        )
        unassigned = PlanUnassignedRequest(
            id=uuid.UUID(int=41),
            plan_id=plan.id,
            request_id=urgent.id,
            reason=UnassignedReason.NO_AVAILABLE_ENGINEER,
        )
        states = [
            PlanEngineerState(plan_id=plan.id, engineer_id=used.id, is_available=True),
            PlanEngineerState(plan_id=plan.id, engineer_id=unused.id, is_available=True),
        ]
        used.is_available = False

        snapshot = PlanSnapshotAssembler.build(
            plan, [imported, urgent], [used, unused], states, [stop], [unassigned]
        )

        self.assertEqual(len(snapshot.engineers), 2)
        self.assertEqual({item.request_id for item in snapshot.requests}, {imported.id, urgent.id})
        self.assertEqual(snapshot.metrics.engineers_used_count, 1)
        self.assertEqual(snapshot.metrics.unassigned_requests_count, 1)
        self.assertTrue(
            next(item for item in snapshot.engineers if item.engineer_id == used.id).is_available
        )
        detail = PlanPresenter.build_detail(snapshot, False, None, None, None, time(9), time(18))
        self.assertEqual([item.engineer_id for item in detail.engineers], [used.id, unused.id])
        self.assertEqual(detail.engineers[1].assigned_requests_count, 0)

    async def test_plan_service_loads_requests_by_plan_membership(self) -> None:
        upload_id = uuid.UUID(int=50)
        plan = Plan(
            id=uuid.UUID(int=51),
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 23),
            upload_id=upload_id,
            kind=PlanKind.EVENT_REPLAN,
            approval_status=ApprovalStatus.PENDING,
            based_on_plan_id=uuid.UUID(int=52),
            triggered_by_event_id=uuid.UUID(int=53),
            calculation_cutoff_at=datetime(2026, 9, 23, 12),
            total_mileage_km=Decimal("0"),
            engineers_used_count=0,
            assigned_requests_count=0,
            unassigned_requests_count=1,
            created_at=datetime(2026, 9, 23, 12),
            approved_at=None,
            rejected_at=None,
        )
        engineer = self._engineer(54, upload_id, "Анна")
        included = self._request(55, upload_id)
        cancelled = self._request(56, upload_id)
        unassigned = PlanUnassignedRequest(
            id=uuid.UUID(int=57),
            plan_id=plan.id,
            request_id=included.id,
            reason=UnassignedReason.NO_TIME_SLOT,
        )
        state = PlanEngineerState(
            plan_id=plan.id, engineer_id=engineer.id, is_available=True
        )
        requests = SimpleNamespace(
            get_by_ids=AsyncMock(return_value=[included]),
            get_by_upload_id=AsyncMock(return_value=[included, cancelled]),
        )
        uow = SimpleNamespace(
            plan_stops=SimpleNamespace(get_by_plan_id=AsyncMock(return_value=[])),
            plan_unassigned_requests=SimpleNamespace(
                get_by_plan_id=AsyncMock(return_value=[unassigned])
            ),
            requests=requests,
            engineers=SimpleNamespace(
                get_by_upload_id=AsyncMock(return_value=[engineer]),
                get_by_ids=AsyncMock(return_value=[]),
            ),
            plan_engineer_states=SimpleNamespace(
                get_by_plan_id=AsyncMock(return_value=[state])
            ),
        )

        snapshot = await PlanService(uow)._load_snapshot(plan)

        self.assertEqual([item.request_id for item in snapshot.requests], [included.id])
        requests.get_by_ids.assert_awaited_once_with({included.id})
        requests.get_by_upload_id.assert_not_awaited()

    @staticmethod
    def _engineer(number: int, upload_id: uuid.UUID, name: str) -> Engineer:
        start = datetime(2026, 9, 23, 9)
        return Engineer(
            id=uuid.UUID(int=number),
            upload_id=upload_id,
            name=name,
            region=Region.VOSTOK,
            start_point_address="Офис",
            start_point_latitude=Decimal("55.750000"),
            start_point_longitude=Decimal("37.610000"),
            shift_start=start,
            shift_end=start + timedelta(hours=8),
            skills=[],
            vehicle_type=VehicleType.CAR,
            is_available=True,
        )

    @staticmethod
    def _request(number: int, upload_id: uuid.UUID | None) -> Request:
        start = datetime(2026, 9, 23, 10)
        return Request(
            id=uuid.UUID(int=number),
            upload_id=upload_id,
            external_id=number,
            type_bk=RequestTypeBk.CONNECTION,
            type_hd=RequestTypeHd.CONNECTION_REQUEST,
            region=Region.VOSTOK,
            district="Район",
            address=f"Адрес {number}",
            latitude=Decimal("55.760000"),
            longitude=Decimal("37.620000"),
            connection_type=None,
            is_gigabit=False,
            window_start=start,
            window_end=start + timedelta(hours=2),
            norm_minutes=80,
            norm_minutes_without_travel=60,
            priority=2,
            required_skill=Skill.CONNECTION_AND_ORDERS,
            required_vehicle_type=None,
        )


if __name__ == "__main__":
    unittest.main()
