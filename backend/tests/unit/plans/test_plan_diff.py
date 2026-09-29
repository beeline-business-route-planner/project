import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.api.plans.diff import PlanDiffEngine
from src.api.plans.diff_dto import (
    PlanMetricsDTO,
    PlanSnapshotDTO,
    SnapshotEngineerDTO,
    SnapshotRequestDTO,
)
from src.api.plans.enums import EngineerChange, RequestChange
from src.core.db.enums import (
    ApprovalStatus,
    PlanKind,
    Region,
    Skill,
    UnassignedReason,
    VehicleType,
)


class PlanDiffEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 9, 23, 10)
        self.engineer_one = self._engineer(101, "Анна")
        self.engineer_two = self._engineer(102, "Борис")
        self.request_one = self._request(201, self.engineer_one.engineer_id, 1)
        self.request_two = self._request(202, self.engineer_two.engineer_id, 1)

    def test_identical_plans_are_unchanged(self) -> None:
        before = self._snapshot(
            1,
            (self.request_one, self.request_two),
            (
                replace(self.engineer_one, requests=(self.request_one,)),
                replace(self.engineer_two, requests=(self.request_two,)),
            ),
        )
        after = replace(before, id=self._id(2))

        result = PlanDiffEngine.compare(before, after)

        self.assertTrue(all(item.changes == (RequestChange.UNCHANGED,) for item in result.requests))
        self.assertTrue(all(item.change == EngineerChange.UNCHANGED for item in result.engineers))

    def test_engineer_can_be_added_and_removed(self) -> None:
        before = self._snapshot(1, (), (self.engineer_one,))
        after = self._snapshot(2, (), (self.engineer_two,))

        result = PlanDiffEngine.compare(before, after)

        self.assertEqual(
            [item.change for item in result.engineers],
            [EngineerChange.REMOVED, EngineerChange.ADDED],
        )

    def test_request_can_be_reassigned(self) -> None:
        moved = replace(self.request_one, engineer_id=self.engineer_two.engineer_id)
        before = self._snapshot(
            1,
            (self.request_one,),
            (
                replace(self.engineer_one, requests=(self.request_one,)),
                self.engineer_two,
            ),
        )
        after = self._snapshot(
            2,
            (moved,),
            (
                self.engineer_one,
                replace(self.engineer_two, requests=(moved,)),
            ),
        )

        result = PlanDiffEngine.compare(before, after)

        self.assertIn(RequestChange.REASSIGNED, result.requests[0].changes)

    def test_schedule_only_change_is_detected(self) -> None:
        moved = replace(
            self.request_one,
            planned_arrival=self.request_one.planned_arrival + timedelta(minutes=15),
            planned_start=self.request_one.planned_start + timedelta(minutes=15),
            planned_finish=self.request_one.planned_finish + timedelta(minutes=15),
        )

        result = PlanDiffEngine.compare(
            self._snapshot(1, (self.request_one,), (self.engineer_one,)),
            self._snapshot(2, (moved,), (self.engineer_one,)),
        )

        self.assertEqual(result.requests[0].changes, (RequestChange.RESCHEDULED,))

    def test_travel_only_change_is_detected(self) -> None:
        moved = replace(self.request_one, travel_minutes=25, distance_km=Decimal("8.50"))

        result = PlanDiffEngine.compare(
            self._snapshot(1, (self.request_one,), (self.engineer_one,)),
            self._snapshot(2, (moved,), (self.engineer_one,)),
        )

        self.assertEqual(result.requests[0].changes, (RequestChange.TRAVEL_CHANGED,))

    def test_requests_can_be_added_and_removed(self) -> None:
        before = self._snapshot(1, (self.request_one,), (self.engineer_one,))
        after = self._snapshot(2, (self.request_two,), (self.engineer_two,))

        result = PlanDiffEngine.compare(before, after)

        self.assertEqual(
            [item.changes for item in result.requests],
            [(RequestChange.REMOVED,), (RequestChange.ADDED,)],
        )

    def test_summary_contains_before_after_and_delta(self) -> None:
        unassigned = replace(
            self.request_two,
            engineer_id=None,
            sequence_number=None,
            planned_arrival=None,
            planned_start=None,
            planned_finish=None,
            travel_minutes=None,
            distance_km=None,
            unassigned_reason=UnassignedReason.NO_TIME_SLOT,
        )
        before = self._snapshot(1, (self.request_one,), (self.engineer_one,))
        after = self._snapshot(
            2,
            (self.request_one, unassigned),
            (replace(self.engineer_one, requests=(self.request_one,)),),
        )

        result = PlanDiffEngine.compare(before, after)

        self.assertEqual(result.summary.assigned_requests.before, 1)
        self.assertEqual(result.summary.assigned_requests.after, 1)
        self.assertEqual(result.summary.assigned_requests.delta, 0)
        self.assertEqual(result.summary.unassigned_requests.before, 0)
        self.assertEqual(result.summary.unassigned_requests.after, 1)
        self.assertEqual(result.summary.unassigned_requests.delta, 1)

    def test_assigned_request_can_become_unassigned_and_back(self) -> None:
        unassigned = replace(
            self.request_one,
            engineer_id=None,
            sequence_number=None,
            planned_arrival=None,
            planned_start=None,
            planned_finish=None,
            travel_minutes=None,
            distance_km=None,
            unassigned_reason=UnassignedReason.NO_TIME_SLOT,
        )
        assigned_to_unassigned = PlanDiffEngine.compare(
            self._snapshot(1, (self.request_one,), (self.engineer_one,)),
            self._snapshot(2, (unassigned,), (self.engineer_one,)),
        )
        unassigned_to_assigned = PlanDiffEngine.compare(
            self._snapshot(3, (unassigned,), (self.engineer_one,)),
            self._snapshot(4, (self.request_one,), (self.engineer_one,)),
        )

        self.assertIn(
            RequestChange.ASSIGNMENT_CHANGED,
            assigned_to_unassigned.requests[0].changes,
        )
        self.assertIn(
            RequestChange.ASSIGNMENT_CHANGED,
            unassigned_to_assigned.requests[0].changes,
        )

    def test_input_order_does_not_change_result(self) -> None:
        second_for_first = replace(
            self.request_two,
            engineer_id=self.engineer_one.engineer_id,
            sequence_number=2,
        )
        engineers = (
            replace(self.engineer_one, requests=(self.request_one, second_for_first)),
            self.engineer_two,
        )
        ordered = PlanDiffEngine.compare(
            self._snapshot(1, (self.request_one, second_for_first), engineers),
            self._snapshot(2, (self.request_one, second_for_first), engineers),
        )
        shuffled_engineers = (
            self.engineer_two,
            replace(
                self.engineer_one,
                requests=(second_for_first, self.request_one),
            ),
        )
        shuffled = PlanDiffEngine.compare(
            self._snapshot(1, (second_for_first, self.request_one), shuffled_engineers),
            self._snapshot(2, (second_for_first, self.request_one), shuffled_engineers),
        )

        self.assertEqual(ordered, shuffled)

    def _request(
        self, number: int, engineer_id: uuid.UUID | None, sequence: int | None
    ) -> SnapshotRequestDTO:
        assigned = engineer_id is not None
        return SnapshotRequestDTO(
            request_id=self._id(number),
            external_id=number,
            address=f"Адрес {number}",
            district="Район",
            latitude=Decimal("55.750000"),
            longitude=Decimal("37.610000"),
            window_start=self.base_time,
            window_end=self.base_time + timedelta(hours=2),
            priority=2,
            required_skill=Skill.CONNECTION_AND_ORDERS,
            service_minutes=60,
            engineer_id=engineer_id,
            sequence_number=sequence,
            planned_arrival=self.base_time if assigned else None,
            planned_start=self.base_time if assigned else None,
            planned_finish=self.base_time + timedelta(hours=1) if assigned else None,
            travel_minutes=10 if assigned else None,
            distance_km=Decimal("5.00") if assigned else None,
            is_locked=False,
            unassigned_reason=None if assigned else UnassignedReason.NO_AVAILABLE_ENGINEER,
        )

    def _engineer(self, number: int, name: str) -> SnapshotEngineerDTO:
        return SnapshotEngineerDTO(
            engineer_id=self._id(number),
            name=name,
            vehicle_type=VehicleType.CAR,
            shift_start=self.base_time,
            shift_end=self.base_time + timedelta(hours=8),
            start_latitude=Decimal("55.750000"),
            start_longitude=Decimal("37.610000"),
            is_available=True,
            route_distance_km=Decimal("0"),
            workload_without_travel=Decimal("0"),
            workload_with_travel=Decimal("0"),
            requests=(),
        )

    def _snapshot(
        self,
        number: int,
        requests: tuple[SnapshotRequestDTO, ...],
        engineers: tuple[SnapshotEngineerDTO, ...],
    ) -> PlanSnapshotDTO:
        assigned = sum(item.engineer_id is not None for item in requests)
        return PlanSnapshotDTO(
            id=self._id(number),
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 23),
            kind=PlanKind.REPLAN,
            approval_status=ApprovalStatus.PENDING,
            created_at=self.base_time,
            approved_at=None,
            rejected_at=None,
            calculation_cutoff_at=self.base_time,
            based_on_plan_id=self._id(999),
            triggered_by_event_id=None,
            metrics=PlanMetricsDTO(
                assigned_requests_count=assigned,
                unassigned_requests_count=len(requests) - assigned,
                engineers_used_count=sum(bool(item.requests) for item in engineers),
                available_engineers_count=len(engineers),
                total_mileage_km=sum(
                    (item.distance_km or Decimal("0") for item in requests), Decimal("0")
                ),
                total_work_minutes=sum(
                    item.service_minutes for item in requests if item.engineer_id is not None
                ),
                total_travel_minutes=sum(item.travel_minutes or 0 for item in requests),
                average_workload_without_travel=Decimal("10"),
                average_workload_with_travel=Decimal("12"),
                average_used_workload_without_travel=Decimal("10"),
                average_used_workload_with_travel=Decimal("12"),
                min_workload_with_travel=Decimal("0"),
                max_workload_with_travel=Decimal("12"),
            ),
            requests=requests,
            engineers=engineers,
        )

    @staticmethod
    def _id(number: int) -> uuid.UUID:
        return uuid.UUID(int=number)


if __name__ == "__main__":
    unittest.main()
