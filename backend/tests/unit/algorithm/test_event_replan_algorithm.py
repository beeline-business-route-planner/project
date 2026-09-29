import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import patch

from src.core.algorithm import (
    AlgorithmInputError,
    AlgorithmService,
    AlgorithmVariant,
    BasePlanStop,
    EngineerSnapshot,
    LayerMatrix,
    ReplanDraft,
    ReplanEvent,
    ReplanResult,
    ReplanSnapshot,
    RequestSnapshot,
)
from src.core.db.enums import (
    DistributionMode,
    Region,
    ReplanningEventType,
    RequestStatus,
    Skill,
    VehicleType,
)


class _FlatMatrix:
    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int:
        return 10

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal:
        return Decimal("3.0")


class EventReplanTest(unittest.TestCase):
    day = date(2026, 9, 25)
    first = uuid.UUID(int=1)
    second = uuid.UUID(int=2)
    done_id = uuid.UUID(int=11)
    on_way_id = uuid.UUID(int=12)
    later_id = uuid.UUID(int=13)
    other_id = uuid.UUID(int=14)
    cutoff = datetime(2026, 9, 25, 13)

    def test_urgent_emergency_sla_counts_from_event(self) -> None:
        urgent = RequestSnapshot(
            id=uuid.UUID(int=99),
            latitude=Decimal("55.70"),
            longitude=Decimal("37.60"),
            window_start=datetime(2026, 9, 25, 0, 1),
            window_end=datetime(2026, 9, 25, 23, 59),
            service_minutes=80,
            priority=1,
            required_skill=Skill.LOCAL_WORKS,
            required_vehicle_type=None,
        )
        draft = self._draft(
            ReplanEvent(ReplanningEventType.URGENT_REQUEST, self.cutoff, urgent_request=urgent)
        )

        job = next(job for job in draft.tail.jobs if job.id == urgent.id)
        self.assertEqual(
            (job.release_at, job.latest_start_at), (self.cutoff, datetime(2026, 9, 25, 15))
        )
        result = self._plan(draft)
        self.assertIn(
            urgent.id, {stop.request_id for route in result.routes for stop in route.stops}
        )

    def test_cancel_on_the_way_removes_stop_and_restarts_from_previous_point(self) -> None:
        draft = self._draft(
            ReplanEvent(
                ReplanningEventType.REQUEST_CANCELLED, self.cutoff, request_id=self.on_way_id
            )
        )

        self.assertEqual([stop.request_id for stop in draft.locked_stops], [self.done_id])
        self.assertEqual(draft.cancelled_request_ids, frozenset({self.on_way_id}))
        engineer = next(item for item in draft.tail.engineers if item.id == self.first)
        self.assertEqual(engineer.available_from, self.cutoff)
        result = self._plan(draft)
        self.assertIn(self.on_way_id, result.cancelled_request_ids)

    def test_started_request_cannot_be_cancelled(self) -> None:
        with self.assertRaises(AlgorithmInputError):
            self._draft(
                ReplanEvent(
                    ReplanningEventType.REQUEST_CANCELLED, self.cutoff, request_id=self.done_id
                )
            )

    def test_unavailable_engineer_releases_on_the_way_and_keeps_done(self) -> None:
        draft = self._draft(
            ReplanEvent(
                ReplanningEventType.ENGINEER_UNAVAILABLE, self.cutoff, engineer_id=self.first
            )
        )

        self.assertEqual([stop.request_id for stop in draft.locked_stops], [self.done_id])
        self.assertIn(self.on_way_id, {job.id for job in draft.tail.jobs})
        result = self._plan(draft)
        first_route = next(route for route in result.routes if route.engineer_id == self.first)
        self.assertTrue(all(stop.is_locked for stop in first_route.stops))

    def test_returned_engineer_starts_from_own_start_point(self) -> None:
        snapshot = self._snapshot()
        snapshot = replace(
            snapshot,
            engineers=tuple(
                replace(item, is_available=False) if item.id == self.first else item
                for item in snapshot.engineers
            ),
            requests=tuple(
                replace(item, status=RequestStatus.NOT_SENT) if item.id == self.on_way_id else item
                for item in snapshot.requests
            ),
            base_stops=tuple(
                stop
                for stop in snapshot.base_stops
                if stop.request_id in {self.done_id, self.other_id}
            ),
        )
        draft = AlgorithmService().prepare_event_replan(
            snapshot,
            ReplanEvent(
                ReplanningEventType.ENGINEER_AVAILABLE, self.cutoff, engineer_id=self.first
            ),
        )

        engineer = next(item for item in draft.tail.engineers if item.id == self.first)
        self.assertEqual(
            (engineer.start_latitude, engineer.start_longitude, engineer.available_from),
            (Decimal("55.75"), Decimal("37.61"), self.cutoff),
        )
        self.assertEqual(engineer.history_service_minutes, 60)
        self._plan(draft)

    def test_cancel_keeps_rest_of_current_plan_as_known_solution(self) -> None:
        draft = self._draft(
            ReplanEvent(
                ReplanningEventType.REQUEST_CANCELLED, self.cutoff, request_id=self.later_id
            )
        )

        with patch("src.core.algorithm.service.GreedyPlanner.assign", return_value={}):
            result = self._plan(draft, AlgorithmVariant.GREEDY)

        second_route = next(route for route in result.routes if route.engineer_id == self.second)
        self.assertEqual([stop.request_id for stop in second_route.stops], [self.other_id])

    def test_event_after_cutoff_is_rejected(self) -> None:
        with self.assertRaises(AlgorithmInputError):
            self._draft(
                ReplanEvent(
                    ReplanningEventType.ENGINEER_UNAVAILABLE,
                    datetime(2026, 9, 25, 13, 1),
                    engineer_id=self.first,
                )
            )

    def _draft(self, event: ReplanEvent) -> ReplanDraft:
        return AlgorithmService().prepare_event_replan(self._snapshot(), event)

    def _plan(
        self, draft: ReplanDraft, variant: AlgorithmVariant = AlgorithmVariant.LAYERED_GRAPH
    ) -> ReplanResult:
        service = AlgorithmService()
        replan_input = service.build_replan_input(
            draft,
            [
                LayerMatrix(request=request, travel_matrix=_FlatMatrix())
                for request in draft.tail.matrix_requests
            ],
        )
        return service.plan_replan(replan_input, variant)

    def _snapshot(self) -> ReplanSnapshot:
        return ReplanSnapshot(
            region=Region.VOSTOK,
            planning_date=self.day,
            calculation_cutoff_at=self.cutoff,
            mode=DistributionMode.MIN_ENGINEERS,
            requests=(
                self._request(self.done_id, time(10), RequestStatus.DONE),
                self._request(self.on_way_id, time(12), RequestStatus.ON_THE_WAY),
                self._request(self.later_id, time(14), RequestStatus.NOT_SENT),
                self._request(self.other_id, time(14), RequestStatus.NOT_SENT),
            ),
            engineers=(self._engineer(self.first), self._engineer(self.second)),
            base_stops=(
                self._stop(self.first, self.done_id, 1, time(10, 10)),
                self._stop(self.first, self.on_way_id, 2, time(13, 20)),
                self._stop(self.first, self.later_id, 3, time(14, 40)),
                self._stop(self.second, self.other_id, 1, time(14)),
            ),
        )

    def _request(
        self, request_id: uuid.UUID, start: time, status: RequestStatus
    ) -> RequestSnapshot:
        return RequestSnapshot(
            id=request_id,
            latitude=Decimal("55.76"),
            longitude=Decimal("37.62"),
            window_start=datetime.combine(self.day, start),
            window_end=datetime.combine(self.day, time(start.hour + 2)),
            service_minutes=60,
            priority=3,
            required_skill=Skill.LOCAL_WORKS,
            required_vehicle_type=None,
            status=status,
        )

    def _engineer(self, engineer_id: uuid.UUID) -> EngineerSnapshot:
        return EngineerSnapshot(
            id=engineer_id,
            start_latitude=Decimal("55.75"),
            start_longitude=Decimal("37.61"),
            shift_start=datetime.combine(self.day, time(10)),
            shift_end=datetime.combine(self.day, time(22)),
            skills=frozenset({Skill.LOCAL_WORKS}),
            vehicle_type=VehicleType.CAR,
            is_available=True,
        )

    def _stop(
        self, engineer_id: uuid.UUID, request_id: uuid.UUID, sequence: int, start: time
    ) -> BasePlanStop:
        planned = datetime.combine(self.day, start)
        return BasePlanStop(
            engineer_id=engineer_id,
            request_id=request_id,
            sequence_number=sequence,
            arrival=planned.replace(minute=0) if start.minute >= 10 else planned,
            start=planned,
            finish=planned.replace(hour=start.hour + 1),
            travel_minutes=10,
            distance_km=Decimal("3.0"),
        )
