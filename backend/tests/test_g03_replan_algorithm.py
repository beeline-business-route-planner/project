import unittest
import uuid
from datetime import date, datetime
from decimal import Decimal

from src.core.algorithm import (
    AlgorithmService,
    BasePlanStop,
    DistributionMode,
    EngineerSnapshot,
    ReplanSnapshot,
    RequestSnapshot,
)
from src.core.db.enums import Region, RequestStatus, Skill, VehicleType


class ReplanDepartureLockTest(unittest.TestCase):
    def test_stop_is_locked_when_travel_started_before_cutoff(self) -> None:
        planning_date = date(2026, 9, 25)
        cutoff = datetime(2026, 9, 25, 13, 45)
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
        snapshot = ReplanSnapshot(
            region=Region.VOSTOK,
            planning_date=planning_date,
            calculation_cutoff_at=cutoff,
            mode=DistributionMode.MIN_ENGINEERS,
            requests=(
                RequestSnapshot(
                    id=request_id,
                    latitude=Decimal("55.75"),
                    longitude=Decimal("37.61"),
                    window_start=datetime(2026, 9, 25, 14),
                    window_end=datetime(2026, 9, 25, 16),
                    service_minutes=30,
                    priority=2,
                    required_skill=Skill.CONNECTION_AND_ORDERS,
                    required_vehicle_type=None,
                    status=RequestStatus.NOT_SENT,
                ),
            ),
            engineers=(
                EngineerSnapshot(
                    id=engineer_id,
                    start_latitude=Decimal("55.75"),
                    start_longitude=Decimal("37.61"),
                    shift_start=datetime(2026, 9, 25, 10),
                    shift_end=datetime(2026, 9, 25, 22),
                    skills=frozenset({Skill.CONNECTION_AND_ORDERS}),
                    vehicle_type=VehicleType.CAR,
                    is_available=True,
                ),
            ),
            base_stops=(stop,),
        )

        draft = AlgorithmService().prepare_replan(snapshot)

        self.assertEqual(draft.locked_stops, (stop,))
        self.assertEqual(draft.tail.jobs, ())
