import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from pydantic import ValidationError
from src.api.exc.planning import PlanningCurrentPlanMissing
from src.api.planning.dto import ReplanRegionResult
from src.api.planning.schemas import ReplanPlanningRequest
from src.api.planning.service import PlanningService
from src.core.algorithm.dto import PlanMetrics, ReplanResult, Route, Stop
from src.core.algorithm.enums import DistributionMode
from src.core.db.enums import PlanKind, Region


class ReplanOrchestrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.uow = SimpleNamespace(
            plans=SimpleNamespace(create=Mock(return_value=uuid.UUID(int=10))),
            plan_engineer_states=SimpleNamespace(add_many=Mock()),
            plan_stops=SimpleNamespace(add_many=Mock()),
            plan_unassigned_requests=SimpleNamespace(add_many=Mock()),
            flush=AsyncMock(),
        )
        self.service = PlanningService(self.uow, None, None, None, None)

    async def test_replan_keeps_successful_regions_after_failure(self) -> None:
        regions = [Region.VOSTOK, Region.YUGO_VOSTOK, Region.YUGOTSENTR]
        self.service._run_replan_region = AsyncMock(
            side_effect=[
                ReplanRegionResult(region=regions[0], status="success"),
                ReplanRegionResult(
                    region=regions[1],
                    status="error",
                    error_code="routing_unavailable",
                    error_detail="Маршрутизация недоступна",
                ),
                ReplanRegionResult(region=regions[2], status="success"),
            ]
        )

        result = await self.service.replan(regions)

        self.assertEqual(result.status, "partial_success")
        self.assertEqual([item.status for item in result.regions], ["success", "error", "success"])
        self.assertEqual(self.service._run_replan_region.await_count, 3)

    async def test_persist_full_candidate_with_locked_history(self) -> None:
        base_id = uuid.UUID(int=1)
        engineer_id = uuid.UUID(int=2)
        request_id = uuid.UUID(int=3)
        cutoff = datetime(2026, 9, 25, 12)
        base = SimpleNamespace(
            base_plan_id=base_id,
            upload_id=uuid.UUID(int=4),
            engineers=(SimpleNamespace(id=engineer_id),),
            engineer_states=(SimpleNamespace(engineer_id=engineer_id, is_available=True),),
        )
        stop = Stop(
            request_id=request_id,
            sequence_number=1,
            arrival=cutoff,
            start=cutoff,
            finish=cutoff,
            travel_minutes=5,
            distance_km=Decimal("1.0"),
            is_locked=True,
        )
        calculated = ReplanResult(
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 25),
            calculation_cutoff_at=cutoff,
            mode=DistributionMode.MIN_ENGINEERS,
            routes=(
                Route(
                    engineer_id=engineer_id,
                    stops=(stop,),
                    service_minutes=0,
                    travel_minutes=5,
                    distance_km=Decimal("1.0"),
                    utilization_without_travel=Decimal("0"),
                    utilization_with_travel=Decimal("0"),
                ),
            ),
            unassigned=(),
            cancelled_request_ids=(),
            metrics=PlanMetrics(
                engineers_available_count=1,
                assigned_requests_count=1,
                unassigned_requests_count=0,
                engineers_used_count=1,
                total_service_minutes=0,
                total_travel_minutes=5,
                total_mileage_km=Decimal("1.0"),
                average_utilization_with_travel=Decimal("0"),
                average_utilization_without_travel=Decimal("0"),
            ),
            algorithm_version="test",
        )

        plan_id = await self.service._persist_replan_result(base, calculated)

        self.assertEqual(plan_id, uuid.UUID(int=10))
        saved_plan = self.uow.plans.create.call_args.args[0]
        self.assertEqual(saved_plan.kind, PlanKind.REPLAN)
        self.assertEqual(saved_plan.based_on_plan_id, base_id)
        self.assertEqual(saved_plan.upload_id, base.upload_id)
        self.assertEqual(saved_plan.calculation_cutoff_at, cutoff)
        self.assertTrue(self.uow.plan_stops.add_many.call_args.args[0][0].is_locked)
        self.assertEqual(self.uow.plan_stops.add_many.call_args.args[0][0].request_id, request_id)
        self.assertEqual(len(self.uow.plan_engineer_states.add_many.call_args.args[0]), 1)

        cancelled = replace(
            calculated,
            routes=(),
            cancelled_request_ids=(request_id,),
            metrics=replace(
                calculated.metrics,
                assigned_requests_count=0,
                engineers_used_count=0,
                total_mileage_km=Decimal("0"),
            ),
        )
        await self.service._persist_replan_result(base, cancelled)
        self.assertEqual(self.uow.plan_stops.add_many.call_args.args[0], [])
        self.assertEqual(self.uow.plan_unassigned_requests.add_many.call_args.args[0], [])

    async def test_region_success_commits_pending_candidate(self) -> None:
        base_id = uuid.UUID(int=1)
        plan_id = uuid.UUID(int=10)
        base = SimpleNamespace(base_plan_id=base_id)
        plan = SimpleNamespace(
            id=plan_id,
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 25),
            created_at=datetime(2026, 9, 25, 9),
            assigned_requests_count=1,
            unassigned_requests_count=0,
            engineers_used_count=1,
            total_mileage_km=Decimal("1.0"),
        )
        self.uow.plans.lock_region_day = AsyncMock()
        self.uow.plans.get_by_id = AsyncMock(return_value=plan)
        self.uow.commit = AsyncMock()
        self.uow.rollback = AsyncMock()
        self.service.prepare_replan_base = AsyncMock(return_value=base)
        self.service._to_replan_snapshot = Mock(return_value=object())
        self.service._persist_replan_result = AsyncMock(return_value=plan_id)
        self.service._algorithm = SimpleNamespace(
            prepare_replan=Mock(
                return_value=SimpleNamespace(tail=SimpleNamespace(points=(), matrix_requests=()))
            ),
            build_replan_input=Mock(return_value=object()),
            plan_replan=Mock(return_value=object()),
        )

        result = await self.service._run_replan_region(Region.VOSTOK)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.plan_summary.based_on_plan_id, base_id)
        self.uow.commit.assert_awaited_once()
        self.uow.rollback.assert_not_awaited()
        self.uow.plans.lock_region_day.assert_awaited_once()

    async def test_missing_current_rolls_back_only_its_region(self) -> None:
        self.uow.plans.lock_region_day = AsyncMock()
        self.uow.rollback = AsyncMock()
        self.service.prepare_replan_base = AsyncMock(side_effect=PlanningCurrentPlanMissing)

        result = await self.service._run_replan_region(Region.VOSTOK)

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "current_plan_missing")
        self.uow.rollback.assert_awaited_once()
        self.uow.plans.create.assert_not_called()

    def test_region_input_requires_unique_nonempty_regions(self) -> None:
        with self.assertRaises(ValidationError):
            ReplanPlanningRequest(regions=[])
        with self.assertRaises(ValidationError):
            ReplanPlanningRequest(regions=[Region.VOSTOK, Region.VOSTOK])
