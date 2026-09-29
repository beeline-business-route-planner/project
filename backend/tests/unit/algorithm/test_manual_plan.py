import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal

from src.core.algorithm import (
    AlgorithmInputError,
    AlgorithmService,
    EngineerSnapshot,
    InitialPlanningSnapshot,
    LayerMatrix,
    RequestSnapshot,
)
from src.core.algorithm.enums import ManualIssueCode
from src.core.algorithm.exc import ManualRouteViolationError
from src.core.db.enums import DistributionMode, Region, Skill, VehicleType


class _Matrix:
    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int:
        del from_id, to_id
        return 10

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal:
        del from_id, to_id
        return Decimal("1.25")


class ManualPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.day = date(2026, 9, 25)
        self.engineer_id = uuid.UUID(int=1)
        self.first_id = uuid.UUID(int=2)
        self.second_id = uuid.UUID(int=3)
        self.service = AlgorithmService()
        self.engineer = EngineerSnapshot(
            id=self.engineer_id,
            start_latitude=Decimal("55.75"),
            start_longitude=Decimal("37.61"),
            shift_start=datetime.combine(self.day, time(10)),
            shift_end=datetime.combine(self.day, time(22)),
            skills=frozenset({Skill.LOCAL_WORKS}),
            vehicle_type=VehicleType.CAR,
            is_available=True,
        )
        draft = self.service.prepare_initial(
            InitialPlanningSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, time(9)),
                mode=DistributionMode.BALANCED,
                requests=(self._request(self.first_id), self._request(self.second_id)),
                engineers=(self.engineer,),
            )
        )
        self.planning_input = self.service.build_initial_input(
            draft, [LayerMatrix(item, _Matrix()) for item in draft.matrix_requests]
        )

    def test_order_is_materialized_and_audited(self) -> None:
        result = self.service.plan_manual_initial(
            self.planning_input, {self.engineer_id: (self.second_id, self.first_id)}
        )
        self.assertEqual(
            tuple(stop.request_id for stop in result.routes[0].stops),
            (self.second_id, self.first_id),
        )
        self.assertEqual(result.metrics.total_mileage_km, Decimal("2.50"))
        self.assertEqual(result.metrics.assigned_requests_count, 2)

    def test_duplicate_request_is_rejected(self) -> None:
        with self.assertRaises(AlgorithmInputError):
            self.service.plan_manual_initial(
                self.planning_input, {self.engineer_id: (self.first_id, self.first_id)}
            )

    def test_skill_mismatch_is_rejected(self) -> None:
        other = self._request(self.second_id, skill=Skill.EMERGENCY_WORKS)
        draft = self.service.prepare_initial(
            InitialPlanningSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, time(9)),
                mode=DistributionMode.BALANCED,
                requests=(other,),
                engineers=(self.engineer,),
            )
        )
        planning_input = self.service.build_initial_input(
            draft, [LayerMatrix(item, _Matrix()) for item in draft.matrix_requests]
        )
        with self.assertRaises(AlgorithmInputError):
            self.service.plan_manual_initial(planning_input, {self.engineer_id: (self.second_id,)})

    def test_late_requests_are_identified_individually(self) -> None:
        planning_input = replace(
            self.planning_input,
            calculation_cutoff_at=datetime.combine(self.day, time(14, 5)),
        )
        with self.assertRaises(ManualRouteViolationError) as caught:
            self.service.plan_manual_initial(
                planning_input, {self.engineer_id: (self.first_id, self.second_id)}
            )
        issues = caught.exception.diagnosis.issues
        self.assertEqual({item.request_id for item in issues}, {self.first_id, self.second_id})
        self.assertTrue(all(item.code == ManualIssueCode.WINDOW_PASSED for item in issues))
        self.assertTrue(all(item.at is not None and item.limit is not None for item in issues))

    def _request(self, request_id: uuid.UUID, skill: Skill = Skill.LOCAL_WORKS) -> RequestSnapshot:
        return RequestSnapshot(
            id=request_id,
            latitude=Decimal("55.76"),
            longitude=Decimal("37.62"),
            window_start=datetime.combine(self.day, time(10)),
            window_end=datetime.combine(self.day, time(14)),
            service_minutes=30,
            priority=3,
            required_skill=skill,
            required_vehicle_type=None,
        )
