import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal

from src.core.algorithm import (
    AlgorithmService,
    BasePlanStop,
    EngineerSnapshot,
    InitialPlanningSnapshot,
    Job,
    ReplanSnapshot,
    RequestSnapshot,
)
from src.core.db.enums import DistributionMode, Region, Skill, VehicleType


class EmergencySlaTest(unittest.TestCase):
    day = date(2026, 9, 25)
    engineer_id = uuid.UUID(int=1)
    request_id = uuid.UUID(int=2)

    def test_emergency_sla_counts_from_cutoff_not_before_operational_day(self) -> None:
        cases = (
            (time(9), time(10), time(12)),
            (time(10, 30), time(10, 30), time(12, 30)),
            (time(11, 5), time(11, 5), time(13, 5)),
            (time(21, 30), time(21, 30), time(23, 30)),
        )
        for cutoff, release, latest in cases:
            with self.subTest(cutoff=cutoff):
                job = self._initial_job(self._emergency(), cutoff)

                self.assertEqual(
                    (job.release_at.time(), job.latest_start_at.time()), (release, latest)
                )

    def test_client_window_bounds_emergency_sla(self) -> None:
        request = replace(
            self._emergency(),
            window_start=datetime.combine(self.day, time(15)),
            window_end=datetime.combine(self.day, time(17)),
        )
        for cutoff, release, latest in (
            (time(9, 30), time(15), time(17)),
            (time(15, 30), time(15, 30), time(17)),
        ):
            with self.subTest(cutoff=cutoff):
                job = self._initial_job(request, cutoff)

                self.assertEqual(
                    (job.release_at.time(), job.latest_start_at.time()), (release, latest)
                )

    def test_replan_keeps_sla_of_emergency_received_at_initial(self) -> None:
        stop = BasePlanStop(
            engineer_id=self.engineer_id,
            request_id=self.request_id,
            sequence_number=1,
            arrival=datetime.combine(self.day, time(11, 20)),
            start=datetime.combine(self.day, time(11, 30)),
            finish=datetime.combine(self.day, time(12, 50)),
            travel_minutes=20,
            distance_km=Decimal("5.0"),
        )
        job = self._replan_job(time(11, 10), (stop,))

        self.assertEqual((job.release_at.time(), job.latest_start_at.time()), (time(10), time(12)))

    def test_expired_sla_restarts_from_replan_cutoff(self) -> None:
        job = self._replan_job(time(12, 30), ())

        self.assertEqual(
            (job.release_at.time(), job.latest_start_at.time()), (time(12, 30), time(14, 30))
        )

    def test_expired_client_window_is_not_restarted_past_its_end(self) -> None:
        request = replace(
            self._emergency(),
            window_start=datetime.combine(self.day, time(14)),
            window_end=datetime.combine(self.day, time(16)),
        )
        job = self._initial_job(request, time(20))

        self.assertEqual((job.release_at.time(), job.latest_start_at.time()), (time(14), time(16)))

    def test_layers_with_same_start_see_each_other_as_sources(self) -> None:
        short = replace(
            self._emergency(),
            window_start=datetime.combine(self.day, time(12)),
            window_end=datetime.combine(self.day, time(13)),
            priority=2,
        )
        long = replace(short, id=uuid.UUID(int=3), window_end=datetime.combine(self.day, time(14)))
        draft = AlgorithmService().prepare_initial(
            InitialPlanningSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, time(9)),
                mode=DistributionMode.MIN_ENGINEERS,
                requests=(short, long),
                engineers=(self._engineer(),),
            )
        )

        self.assertEqual(
            [request.source_ids for request in draft.matrix_requests],
            [frozenset({self.engineer_id, short.id, long.id})] * 2,
        )

    def _initial_job(self, request: RequestSnapshot, cutoff: time) -> Job:
        draft = AlgorithmService().prepare_initial(
            InitialPlanningSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, cutoff),
                mode=DistributionMode.MIN_ENGINEERS,
                requests=(request,),
                engineers=(self._engineer(),),
            )
        )
        return draft.jobs[0]

    def _replan_job(self, cutoff: time, base_stops: tuple[BasePlanStop, ...]) -> Job:
        draft = AlgorithmService().prepare_replan(
            ReplanSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, cutoff),
                mode=DistributionMode.MIN_ENGINEERS,
                requests=(
                    replace(self._emergency(), received_at=datetime.combine(self.day, time(9, 30))),
                ),
                engineers=(self._engineer(),),
                base_stops=base_stops,
            )
        )
        return draft.tail.jobs[0]

    def _emergency(self) -> RequestSnapshot:
        return RequestSnapshot(
            id=self.request_id,
            latitude=Decimal("55.75"),
            longitude=Decimal("37.61"),
            window_start=datetime.combine(self.day, time(0, 1)),
            window_end=datetime.combine(self.day, time(23, 59)),
            service_minutes=80,
            priority=1,
            required_skill=Skill.EMERGENCY_WORKS,
            required_vehicle_type=None,
        )

    def _engineer(self) -> EngineerSnapshot:
        return EngineerSnapshot(
            id=self.engineer_id,
            start_latitude=Decimal("55.70"),
            start_longitude=Decimal("37.50"),
            shift_start=datetime.combine(self.day, time(10)),
            shift_end=datetime.combine(self.day, time(22)),
            skills=frozenset({Skill.EMERGENCY_WORKS}),
            vehicle_type=VehicleType.CAR,
            is_available=True,
        )
