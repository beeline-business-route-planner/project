"""Ручной initial и правка алгоритмического replan на одноразовой PostgreSQL."""

import os
import unittest
from datetime import datetime

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from src.api.planning.dto import EventPlanningCommand, ManualPlanCommand, ManualRoute
from src.api.planning.service import PlanningService
from src.api.plans.service import PlanService
from src.core.algorithm import AlgorithmService
from src.core.db.enums import ApprovalStatus, PlanStrategy, Region, ReplanningEventType
from src.core.db.uow import UnitOfWork

from tests.support.planning import MOSCOW, FakeGeocoder, FakeMatrixService, FakeStorage, pair

DATABASE_URL = os.environ.get("MANUAL_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "MANUAL_TEST_DATABASE_URL is not set")
class ManualPlanningEndToEndTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        assert DATABASE_URL is not None
        url = make_url(DATABASE_URL)
        if not (url.database or "").startswith("manual_test_"):
            self.fail("Manual E2E requires disposable manual_test_* database")
        self.engine = create_async_engine(DATABASE_URL)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_manual_initial_and_algorithm_candidate_edit(self) -> None:
        if datetime.now(MOSCOW).hour >= 23:
            self.skipTest("Нужен остаток рабочего дня")
        storage = FakeStorage()
        async with self.sessions() as session:
            service = PlanningService(
                UnitOfWork(session),
                FakeGeocoder(),
                storage,
                AlgorithmService(),
                FakeMatrixService(),
            )
            dataset = await service.import_manual_data(pair("Восток"))
        self.assertEqual(len(dataset.requests), 1)
        command = ManualPlanCommand(
            upload_id=dataset.upload_id,
            source_plan_id=None,
            routes=(ManualRoute(dataset.engineers[0].id, (dataset.requests[0].id,)),),
        )
        async with self.sessions() as session:
            service = PlanningService(
                UnitOfWork(session),
                FakeGeocoder(),
                storage,
                AlgorithmService(),
                FakeMatrixService(),
            )
            preview = await service.preview_manual(command)
            self.assertIsNone(preview.compared_to_plan_id)
            self.assertEqual(preview.assigned_requests_count, 1)
            initial_id = await service.save_manual(command)
        async with self.sessions() as session:
            plans = PlanService(UnitOfWork(session))
            initial = await plans.get_by_id(initial_id)
            self.assertIsNotNone(initial.baseline_metrics)
            await plans.approve(initial_id)

        async with self.sessions() as session:
            service = PlanningService(
                UnitOfWork(session),
                FakeGeocoder(),
                storage,
                AlgorithmService(),
                FakeMatrixService(),
            )
            generated = await service.replan([Region.VOSTOK], None, None)
            source = generated.regions[0].plan_summary
            self.assertIsNotNone(source)
            assert source is not None
            edit = ManualPlanCommand(
                upload_id=None,
                source_plan_id=source.id,
                routes=(ManualRoute(dataset.engineers[0].id, (dataset.requests[0].id,)),),
            )
            comparison = await service.preview_manual(edit)
            self.assertEqual(comparison.compared_to_plan_id, initial_id)
            edited_id = await service.save_manual(edit)
        async with self.sessions() as session:
            plans = PlanService(UnitOfWork(session))
            edited = await plans.get_by_id(edited_id)
            self.assertEqual(edited.edited_from_plan_id, source.id)
            self.assertEqual(
                (await plans.get_by_id(source.id)).approval_status, ApprovalStatus.REJECTED
            )
            await plans.approve(edited_id)
            self.assertEqual((await plans.get_current(Region.VOSTOK)).id, edited_id)
            stored = await UnitOfWork(session).plans.get_by_id(edited_id)
            self.assertEqual(stored.strategy, PlanStrategy.MANUAL)

        async with self.sessions() as session:
            service = PlanningService(
                UnitOfWork(session),
                FakeGeocoder(),
                storage,
                AlgorithmService(),
                FakeMatrixService(),
            )
            event = await service.create_event(
                EventPlanningCommand(
                    region=Region.VOSTOK,
                    event_type=ReplanningEventType.ENGINEER_UNAVAILABLE,
                    request_id=None,
                    engineer_id=dataset.engineers[0].id,
                    urgent_request=None,
                )
            )
        event_edit = ManualPlanCommand(
            upload_id=None,
            source_plan_id=event.plan.id,
            routes=(),
        )
        async with self.sessions() as session:
            service = PlanningService(
                UnitOfWork(session),
                FakeGeocoder(),
                storage,
                AlgorithmService(),
                FakeMatrixService(),
            )
            event_edit_id = await service.save_manual(event_edit)
        async with self.sessions() as session:
            plans = PlanService(UnitOfWork(session))
            self.assertEqual(
                (await plans.get_by_id(event.plan.id)).approval_status, ApprovalStatus.REJECTED
            )
            await plans.approve(event_edit_id)
            self.assertEqual((await plans.get_current(Region.VOSTOK)).id, event_edit_id)

        # Manual planning from fresh workbooks is allowed mid-day, after approvals.
        async with self.sessions() as session:
            service = PlanningService(
                UnitOfWork(session),
                FakeGeocoder(),
                storage,
                AlgorithmService(),
                FakeMatrixService(),
            )
            fresh = await service.import_manual_data(pair("Восток"))
            rebuilt_id = await service.save_manual(
                ManualPlanCommand(
                    upload_id=fresh.upload_id,
                    source_plan_id=None,
                    routes=(ManualRoute(fresh.engineers[0].id, (fresh.requests[0].id,)),),
                )
            )
        async with self.sessions() as session:
            plans = PlanService(UnitOfWork(session))
            await plans.approve(rebuilt_id)
            self.assertEqual((await plans.get_current(Region.VOSTOK)).id, rebuilt_id)
