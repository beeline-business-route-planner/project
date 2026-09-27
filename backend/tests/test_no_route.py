import unittest
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from src.core.algorithm import (
    AlgorithmService,
    AlgorithmVariant,
    EngineerSnapshot,
    InitialPlanningSnapshot,
    LayerMatrix,
    RequestSnapshot,
)
from src.core.db.enums import DistributionMode, Region, Skill, UnassignedReason, VehicleType


class _PartialMatrix:
    """Матрица, в которой часть пар недостижима."""

    def __init__(self, unreachable: set[tuple[uuid.UUID | None, uuid.UUID]]) -> None:
        self._unreachable = unreachable

    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int | None:
        if (from_id, to_id) in self._unreachable or (None, to_id) in self._unreachable:
            return None
        return 10

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal | None:
        return None if self.minutes(from_id, to_id) is None else Decimal("3.0")


class NoRouteTest(unittest.TestCase):
    day = date(2026, 9, 25)
    engineer_id = uuid.UUID(int=1)
    isolated_id = uuid.UUID(int=2)
    partial_id = uuid.UUID(int=3)
    regular_id = uuid.UUID(int=4)

    def test_unreachable_request_is_unassigned_with_no_route(self) -> None:
        service = AlgorithmService()
        draft = service.prepare_initial(
            InitialPlanningSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, time(9)),
                mode=DistributionMode.MIN_ENGINEERS,
                requests=tuple(
                    self._request(request_id)
                    for request_id in (self.isolated_id, self.partial_id, self.regular_id)
                ),
                engineers=(self._engineer(),),
            )
        )
        matrix = _PartialMatrix({(None, self.isolated_id), (self.engineer_id, self.partial_id)})
        planning_input = service.build_initial_input(
            draft, [LayerMatrix(request, matrix) for request in draft.matrix_requests]
        )

        for variant in AlgorithmVariant:
            with self.subTest(variant=variant):
                result = (
                    service.plan_baseline(planning_input)
                    if variant == AlgorithmVariant.BASELINE
                    else service.plan_initial(planning_input, variant)
                )

                reasons = {item.job_id: item.reason for item in result.unassigned}
                self.assertEqual(reasons.get(self.isolated_id), UnassignedReason.NO_ROUTE)
                assigned = {stop.request_id for route in result.routes for stop in route.stops}
                if variant != AlgorithmVariant.BASELINE:
                    self.assertEqual(assigned, {self.partial_id, self.regular_id})

    def _request(self, request_id: uuid.UUID) -> RequestSnapshot:
        return RequestSnapshot(
            id=request_id,
            latitude=Decimal("55.75"),
            longitude=Decimal("37.61"),
            window_start=datetime.combine(self.day, time(10)),
            window_end=datetime.combine(self.day, time(12)),
            service_minutes=30,
            priority=3,
            required_skill=Skill.LOCAL_WORKS,
            required_vehicle_type=None,
        )

    def _engineer(self) -> EngineerSnapshot:
        return EngineerSnapshot(
            id=self.engineer_id,
            start_latitude=Decimal("55.70"),
            start_longitude=Decimal("37.50"),
            shift_start=datetime.combine(self.day, time(10)),
            shift_end=datetime.combine(self.day, time(22)),
            skills=frozenset({Skill.LOCAL_WORKS}),
            vehicle_type=VehicleType.CAR,
            is_available=True,
        )
