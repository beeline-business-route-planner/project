import unittest
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from src.core.algorithm import (
    AlgorithmService,
    EngineerSnapshot,
    InitialPlanningSnapshot,
    LayerMatrix,
    RequestSnapshot,
)
from src.core.db.enums import DistributionMode, Region, Skill, VehicleType


class _ThreeDecimalMatrix:
    """Матрица провайдера с точностью до метра, как у OSRM и 2ГИС."""

    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int:
        return 10

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal:
        return Decimal("1.005") if from_id.int == 1 else Decimal("2.004")


class StopDistanceTest(unittest.TestCase):
    day = date(2026, 9, 25)

    def test_plan_mileage_is_exact_sum_of_stored_stop_distances(self) -> None:
        service = AlgorithmService()
        draft = service.prepare_initial(
            InitialPlanningSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, time(9)),
                mode=DistributionMode.MIN_ENGINEERS,
                requests=(self._request(2), self._request(3)),
                engineers=(
                    EngineerSnapshot(
                        id=uuid.UUID(int=1),
                        start_latitude=Decimal("55.75"),
                        start_longitude=Decimal("37.61"),
                        shift_start=datetime.combine(self.day, time(10)),
                        shift_end=datetime.combine(self.day, time(22)),
                        skills=frozenset({Skill.LOCAL_WORKS}),
                        vehicle_type=VehicleType.CAR,
                        is_available=True,
                    ),
                ),
            )
        )
        result = service.plan_initial(
            service.build_initial_input(
                draft,
                [
                    LayerMatrix(request=request, travel_matrix=_ThreeDecimalMatrix())
                    for request in draft.matrix_requests
                ],
            )
        )

        stops = [stop for route in result.routes for stop in route.stops]
        self.assertEqual(
            sorted(stop.distance_km for stop in stops), [Decimal("1.01"), Decimal("2.00")]
        )
        self.assertEqual(result.metrics.total_mileage_km, sum(stop.distance_km for stop in stops))
        self.assertEqual(result.metrics.total_mileage_km, Decimal("3.01"))

    def _request(self, number: int) -> RequestSnapshot:
        return RequestSnapshot(
            id=uuid.UUID(int=number),
            latitude=Decimal("55.76"),
            longitude=Decimal("37.62"),
            window_start=datetime.combine(self.day, time(10)),
            window_end=datetime.combine(self.day, time(12)),
            service_minutes=30,
            priority=3,
            required_skill=Skill.LOCAL_WORKS,
            required_vehicle_type=None,
        )
