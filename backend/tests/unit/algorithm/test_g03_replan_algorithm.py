import unittest
import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from src.core.algorithm import (
    AlgorithmService,
    AlgorithmVariant,
    BasePlanStop,
    EngineerSnapshot,
    LayerMatrix,
    ReplanSnapshot,
    RequestSnapshot,
)
from src.core.db.enums import DistributionMode, Region, RequestStatus, Skill, VehicleType


class _FlatMatrix:
    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int:
        return 10

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal:
        return Decimal("3.0")


class ReplanLockTest(unittest.TestCase):
    engineer_id = uuid.UUID(int=1)
    request_id = uuid.UUID(int=2)
    stop = BasePlanStop(
        engineer_id=engineer_id,
        request_id=request_id,
        sequence_number=1,
        arrival=datetime(2026, 9, 25, 13, 20),
        start=datetime(2026, 9, 25, 14),
        finish=datetime(2026, 9, 25, 14, 30),
        travel_minutes=20,
        distance_km=Decimal("5.0"),
    )

    def test_started_status_locks_stop_before_planned_start(self) -> None:
        for status in (RequestStatus.ON_THE_WAY, RequestStatus.IN_PROGRESS, RequestStatus.DONE):
            with self.subTest(status=status):
                draft = AlgorithmService().prepare_replan(
                    self._snapshot(datetime(2026, 9, 25, 13, 30), status)
                )

                self.assertEqual(draft.locked_stops, (self.stop,))
                self.assertEqual(draft.tail.jobs, ())

    def test_stop_with_passed_planned_start_is_locked_without_status(self) -> None:
        draft = AlgorithmService().prepare_replan(
            self._snapshot(datetime(2026, 9, 25, 14, 10), RequestStatus.NOT_SENT)
        )

        self.assertEqual(draft.locked_stops, (self.stop,))

    def test_tail_engineer_carries_history_minutes(self) -> None:
        draft = AlgorithmService().prepare_replan(
            self._snapshot(datetime(2026, 9, 25, 14, 10), RequestStatus.NOT_SENT)
        )

        self.assertEqual(
            [engineer.history_service_minutes for engineer in draft.tail.engineers], [30]
        )

    def test_future_stop_without_status_is_replanned(self) -> None:
        draft = AlgorithmService().prepare_replan(
            self._snapshot(datetime(2026, 9, 25, 13, 45), RequestStatus.NOT_SENT)
        )

        self.assertEqual(draft.locked_stops, ())
        self.assertEqual([job.id for job in draft.tail.jobs], [self.request_id])

    def test_replan_is_not_worse_than_feasible_current_future(self) -> None:
        service = AlgorithmService()
        draft = service.prepare_replan(
            self._snapshot(datetime(2026, 9, 25, 13, 45), RequestStatus.NOT_SENT)
        )
        replan_input = service.build_replan_input(
            draft,
            [
                LayerMatrix(request=request, travel_matrix=_FlatMatrix())
                for request in draft.tail.matrix_requests
            ],
        )

        with patch("src.core.algorithm.service.GreedyPlanner.assign", return_value={}):
            result = service.plan_replan(replan_input, AlgorithmVariant.GREEDY)

        self.assertEqual(
            [
                (route.engineer_id, [stop.request_id for stop in route.stops])
                for route in result.routes
            ],
            [(self.engineer_id, [self.request_id])],
        )
        self.assertEqual(result.unassigned, ())

    def _snapshot(self, cutoff: datetime, status: RequestStatus) -> ReplanSnapshot:
        return ReplanSnapshot(
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 25),
            calculation_cutoff_at=cutoff,
            mode=DistributionMode.MIN_ENGINEERS,
            requests=(
                RequestSnapshot(
                    id=self.request_id,
                    latitude=Decimal("55.75"),
                    longitude=Decimal("37.61"),
                    window_start=datetime(2026, 9, 25, 14),
                    window_end=datetime(2026, 9, 25, 16),
                    service_minutes=30,
                    priority=2,
                    required_skill=Skill.CONNECTION_AND_ORDERS,
                    required_vehicle_type=None,
                    status=status,
                ),
            ),
            engineers=(
                EngineerSnapshot(
                    id=self.engineer_id,
                    start_latitude=Decimal("55.75"),
                    start_longitude=Decimal("37.61"),
                    shift_start=datetime(2026, 9, 25, 10),
                    shift_end=datetime(2026, 9, 25, 22),
                    skills=frozenset({Skill.CONNECTION_AND_ORDERS}),
                    vehicle_type=VehicleType.CAR,
                    is_available=True,
                ),
            ),
            base_stops=(self.stop,),
        )
