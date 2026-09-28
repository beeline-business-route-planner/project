import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal

from src.core.algorithm import (
    AlgorithmService,
    AlgorithmVariant,
    BasePlanStop,
    EngineerSnapshot,
    InitialPlanningResult,
    InitialPlanningSnapshot,
    LayerMatrix,
    ReplanResult,
    ReplanSnapshot,
    RequestSnapshot,
)
from src.core.algorithm.audit import ResultAuditor
from src.core.algorithm.exc import AlgorithmAuditError
from src.core.db.enums import (
    DistributionMode,
    Region,
    RequestStatus,
    Skill,
    UnassignedReason,
    VehicleType,
)


class _GridMatrix:
    """Время пропорционально разнице номеров точек: разные переходы стоят по-разному."""

    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int:
        return 5 + abs(from_id.int % 97 - to_id.int % 97)

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal:
        return Decimal(self.minutes(from_id, to_id)) / 3


class AlgorithmEdgeCaseTest(unittest.TestCase):
    day = date(2026, 9, 25)
    variants = tuple(AlgorithmVariant)

    def test_no_requests_gives_empty_plan(self) -> None:
        for variant in self.variants:
            with self.subTest(variant=variant):
                result = self._initial((), (self._engineer(1),), variant)

                self.assertEqual((result.routes, result.unassigned), ((), ()))
                self.assertEqual(result.metrics.total_mileage_km, Decimal("0"))

    def test_no_engineers_leaves_everything_unassigned(self) -> None:
        requests = tuple(self._request(number) for number in range(10, 14))
        for variant in self.variants:
            with self.subTest(variant=variant):
                result = self._initial(requests, (), variant)

                self.assertEqual(result.routes, ())
                self.assertEqual(
                    {item.reason for item in result.unassigned},
                    {UnassignedReason.NO_AVAILABLE_ENGINEER},
                )

    def test_single_engineer_takes_what_fits(self) -> None:
        requests = tuple(self._request(number) for number in range(10, 30))
        for variant in self.variants:
            with self.subTest(variant=variant):
                result = self._initial(requests, (self._engineer(1),), variant)

                self.assertLessEqual(len(result.routes), 1)
                self.assertEqual(
                    result.metrics.assigned_requests_count + len(result.unassigned), 20
                )

    def test_audit_rejects_duplicate_routes_for_one_engineer(self) -> None:
        first_request = self._request(10)
        second_request = self._request(16)
        engineer = self._engineer(1)
        first = self._initial((first_request,), (engineer,), AlgorithmVariant.GREEDY)
        second = self._initial((second_request,), (engineer,), AlgorithmVariant.GREEDY)
        service = AlgorithmService()
        draft = service.prepare_initial(
            InitialPlanningSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, time(9)),
                mode=DistributionMode.MIN_ENGINEERS,
                requests=(first_request, second_request),
                engineers=(engineer,),
            )
        )
        planning_input = service.build_initial_input(
            draft,
            [
                LayerMatrix(request=item, travel_matrix=_GridMatrix())
                for item in draft.matrix_requests
            ],
        )
        routes = first.routes + second.routes
        self.assertEqual(routes[0].stops[0].start, routes[1].stops[0].start)
        invalid = replace(
            first,
            routes=routes,
            unassigned=(),
            metrics=service._metrics(routes, (), planning_input.engineers),
        )
        with self.assertRaises(AlgorithmAuditError):
            ResultAuditor().audit(planning_input, invalid)

    def test_skill_and_vehicle_mismatch_reasons(self) -> None:
        requests = (
            self._request(10, skill=Skill.EMERGENCY_WORKS),
            replace(self._request(11), required_vehicle_type=VehicleType.BICYCLE),
        )
        for variant in self.variants:
            with self.subTest(variant=variant):
                result = self._initial(requests, (self._engineer(1),), variant)

                self.assertEqual(
                    {item.job_id.int: item.reason for item in result.unassigned},
                    {
                        10: UnassignedReason.NO_MATCHING_SKILL,
                        11: UnassignedReason.NO_MATCHING_VEHICLE,
                    },
                )

    def test_cutoff_at_end_of_shift_assigns_nothing(self) -> None:
        requests = tuple(self._request(number) for number in range(10, 14))
        for variant in self.variants:
            with self.subTest(variant=variant):
                result = self._initial(requests, (self._engineer(1),), variant, cutoff=time(21, 50))

                self.assertEqual(result.routes, ())
                self.assertEqual(
                    {item.reason for item in result.unassigned}, {UnassignedReason.NO_TIME_SLOT}
                )

    def test_all_engineers_unavailable(self) -> None:
        requests = tuple(self._request(number) for number in range(10, 14))
        engineers = (replace(self._engineer(1), is_available=False),)
        for variant in self.variants:
            with self.subTest(variant=variant):
                result = self._initial(requests, engineers, variant)

                self.assertEqual(result.metrics.engineers_available_count, 0)
                self.assertEqual(
                    {item.reason for item in result.unassigned},
                    {UnassignedReason.NO_AVAILABLE_ENGINEER},
                )

    def test_initial_is_deterministic_and_ignores_input_order(self) -> None:
        requests = tuple(self._request(number) for number in range(10, 40))
        engineers = tuple(self._engineer(number) for number in range(1, 4))
        for variant in (
            AlgorithmVariant.LAYERED_GRAPH,
            AlgorithmVariant.LNS,
            AlgorithmVariant.GREEDY,
        ):
            with self.subTest(variant=variant):
                first = self._initial(requests, engineers, variant)

                self.assertEqual(self._initial(requests, engineers, variant), first)
                self.assertEqual(
                    self._initial(requests[::-1], engineers[::-1], variant).routes, first.routes
                )

    def test_replan_with_fully_lived_day_keeps_history_only(self) -> None:
        requests = tuple(self._request(number) for number in range(10, 16))
        engineers = (self._engineer(1), self._engineer(2))
        initial = self._initial(requests, engineers, AlgorithmVariant.LAYERED_GRAPH)
        for variant in self.variants:
            with self.subTest(variant=variant):
                result = self._replan(
                    initial,
                    requests,
                    engineers,
                    variant,
                    cutoff=time(21, 59),
                    status=RequestStatus.DONE,
                )

                self.assertTrue(
                    all(stop.is_locked for route in result.routes for stop in route.stops)
                )
                self.assertEqual(
                    result.metrics.assigned_requests_count,
                    initial.metrics.assigned_requests_count,
                )
                self.assertEqual(result.metrics.total_mileage_km, initial.metrics.total_mileage_km)

    def test_replan_with_all_engineers_unavailable(self) -> None:
        requests = tuple(self._request(number) for number in range(10, 16))
        engineers = (self._engineer(1), self._engineer(2))
        initial = self._initial(requests, engineers, AlgorithmVariant.LAYERED_GRAPH)
        unavailable = tuple(replace(item, is_available=False) for item in engineers)
        for variant in self.variants:
            with self.subTest(variant=variant):
                result = self._replan(initial, requests, unavailable, variant, cutoff=time(9))

                self.assertEqual(result.routes, ())
                self.assertEqual(len(result.unassigned), len(requests))

    def test_replan_is_deterministic(self) -> None:
        requests = tuple(self._request(number) for number in range(10, 40))
        engineers = tuple(self._engineer(number) for number in range(1, 4))
        initial = self._initial(requests, engineers, AlgorithmVariant.LAYERED_GRAPH)
        for variant in (AlgorithmVariant.LAYERED_GRAPH, AlgorithmVariant.LNS):
            with self.subTest(variant=variant):
                first = self._replan(initial, requests, engineers, variant, cutoff=time(13))

                self.assertEqual(
                    self._replan(initial, requests, engineers, variant, cutoff=time(13)), first
                )

    def _initial(
        self,
        requests: tuple[RequestSnapshot, ...],
        engineers: tuple[EngineerSnapshot, ...],
        variant: AlgorithmVariant,
        cutoff: time = time(9),
    ) -> InitialPlanningResult:
        service = AlgorithmService()
        draft = service.prepare_initial(
            InitialPlanningSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, cutoff),
                mode=DistributionMode.MIN_ENGINEERS,
                requests=requests,
                engineers=engineers,
            )
        )
        planning_input = service.build_initial_input(
            draft,
            [
                LayerMatrix(request=item, travel_matrix=_GridMatrix())
                for item in draft.matrix_requests
            ],
        )
        if variant == AlgorithmVariant.BASELINE:
            return service.plan_baseline(planning_input)
        return service.plan_initial(planning_input, variant)

    def _replan(
        self,
        initial: InitialPlanningResult,
        requests: tuple[RequestSnapshot, ...],
        engineers: tuple[EngineerSnapshot, ...],
        variant: AlgorithmVariant,
        cutoff: time,
        status: RequestStatus = RequestStatus.NOT_SENT,
    ) -> ReplanResult:
        service = AlgorithmService()
        assigned = {stop.request_id for route in initial.routes for stop in route.stops}
        draft = service.prepare_replan(
            ReplanSnapshot(
                region=Region.VOSTOK,
                planning_date=self.day,
                calculation_cutoff_at=datetime.combine(self.day, cutoff),
                mode=DistributionMode.MIN_ENGINEERS,
                requests=tuple(
                    replace(item, status=status if item.id in assigned else RequestStatus.NOT_SENT)
                    for item in requests
                ),
                engineers=engineers,
                base_stops=tuple(
                    BasePlanStop(
                        engineer_id=route.engineer_id,
                        request_id=stop.request_id,
                        sequence_number=stop.sequence_number,
                        arrival=stop.arrival,
                        start=stop.start,
                        finish=stop.finish,
                        travel_minutes=stop.travel_minutes,
                        distance_km=stop.distance_km,
                    )
                    for route in initial.routes
                    for stop in route.stops
                ),
            )
        )
        return service.plan_replan(
            service.build_replan_input(
                draft,
                [
                    LayerMatrix(request=item, travel_matrix=_GridMatrix())
                    for item in draft.tail.matrix_requests
                ],
            ),
            variant,
        )

    def _request(self, number: int, skill: Skill = Skill.LOCAL_WORKS) -> RequestSnapshot:
        hour = 10 + 2 * (number % 6)
        return RequestSnapshot(
            id=uuid.UUID(int=number),
            latitude=Decimal("55.70") + Decimal(number) / 1000,
            longitude=Decimal("37.60"),
            window_start=datetime.combine(self.day, time(hour)),
            window_end=datetime.combine(self.day, time(hour + 2)),
            service_minutes=30 + 10 * (number % 5),
            priority=2 + number % 2,
            required_skill=skill,
            required_vehicle_type=None,
        )

    def _engineer(self, number: int) -> EngineerSnapshot:
        return EngineerSnapshot(
            id=uuid.UUID(int=number),
            start_latitude=Decimal("55.75"),
            start_longitude=Decimal("37.61"),
            shift_start=datetime.combine(self.day, time(10)),
            shift_end=datetime.combine(self.day, time(22)),
            skills=frozenset({Skill.LOCAL_WORKS}),
            vehicle_type=VehicleType.CAR,
            is_available=True,
        )
