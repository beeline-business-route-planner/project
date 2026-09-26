import os
import unittest
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from src.api.exc.plans import PlanStateChangedError
from src.api.planning.router import import_initial_planning_data, replan
from src.api.planning.schemas import ReplanPlanningRequest
from src.api.planning.service import PlanningService
from src.api.plans.service import PlanService
from src.core.algorithm import AlgorithmService
from src.core.db.enums import ApprovalStatus, Region, RequestStatus
from src.core.db.models import Engineer, PlanStop, Request
from src.core.db.uow import UnitOfWork
from tests.test_g02_initial_e2e import FakeGeocoder, FakeMatrixService, FakeStorage, pair

DATABASE_URL = os.environ.get("T05_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "T05_TEST_DATABASE_URL is not set")
class ReplanEndToEndTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        assert DATABASE_URL is not None
        url = make_url(DATABASE_URL)
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host not in {"127.0.0.1", "localhost"}
            or not (url.database or "").startswith("t05_test_")
        ):
            self.fail("T05 requires a disposable local t05_test_* database")
        self.engine = create_async_engine(
            DATABASE_URL, connect_args={"server_settings": {"timezone": "UTC"}}
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_replan_lifecycle_and_partial_success(self) -> None:
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        if now.hour == 23:
            self.skipTest("For approval, initial needs enough of the working day left")
        storage = FakeStorage()
        files = pair("Восток") + pair("Югоцентр") + pair("Юго-восток")
        uploads = [UploadFile(file=BytesIO(item.data), filename=item.filename) for item in files]
        async with self.sessions() as session:
            initial = await import_initial_planning_data(
                PlanningService(
                    UnitOfWork(session),
                    FakeGeocoder(),
                    storage,
                    AlgorithmService(),
                    FakeMatrixService(),
                ),
                uploads,
            )
        self.assertEqual(initial.status, "success")
        initial_by_region = {item.region: item.plan_summary.id for item in initial.regions}

        async with self.sessions() as session:
            decisions = PlanService(UnitOfWork(session))
            await decisions.approve(initial_by_region[Region.VOSTOK])
            await decisions.approve(initial_by_region[Region.YUGOTSENTR])

        async with self.sessions() as session:
            base_stop = (
                await session.scalars(
                    select(PlanStop).where(PlanStop.plan_id == initial_by_region[Region.VOSTOK])
                )
            ).one()
            request = await session.get(Request, base_stop.request_id)
            assert request is not None
            request.status = RequestStatus.ON_THE_WAY
            await session.commit()

        async with self.sessions() as session:
            result = await replan(
                ReplanPlanningRequest(
                    regions=[Region.VOSTOK, Region.YUGO_VOSTOK, Region.YUGOTSENTR]
                ),
                PlanningService(
                    UnitOfWork(session),
                    FakeGeocoder(),
                    storage,
                    AlgorithmService(),
                    FakeMatrixService(),
                ),
            )
        self.assertEqual(result.status, "partial_success")
        self.assertEqual([item.status for item in result.regions], ["success", "error", "success"])
        self.assertEqual(result.regions[1].error.code, "current_plan_missing")
        east_candidate = result.regions[0].plan_summary.id
        self.assertEqual(
            result.regions[0].plan_summary.based_on_plan_id, initial_by_region[Region.VOSTOK]
        )

        async with self.sessions() as session:
            plans = PlanService(UnitOfWork(session))
            detail = await plans.get_by_id(east_candidate)
            current = await plans.get_current(Region.VOSTOK, now.date())
            history = await plans.list_by_region(Region.VOSTOK)
        self.assertEqual(detail.approval_status, ApprovalStatus.PENDING)
        self.assertEqual(detail.diff.base_plan_id, initial_by_region[Region.VOSTOK])
        self.assertEqual(current.id, initial_by_region[Region.VOSTOK])
        self.assertTrue(any(item.id == east_candidate for item in history))

        async with self.sessions() as session:
            candidate_stops = (
                await session.scalars(select(PlanStop).where(PlanStop.plan_id == east_candidate))
            ).all()
        self.assertEqual(len(candidate_stops), 1)
        self.assertTrue(candidate_stops[0].is_locked)
        self.assertEqual(candidate_stops[0].planned_start, base_stop.planned_start)
        self.assertEqual(candidate_stops[0].planned_finish, base_stop.planned_finish)

        async with self.sessions() as session:
            await PlanService(UnitOfWork(session)).reject(east_candidate)
        async with self.sessions() as session:
            current = await PlanService(UnitOfWork(session)).get_current(Region.VOSTOK, now.date())
        self.assertEqual(current.id, initial_by_region[Region.VOSTOK])

        async def next_east_candidate() -> object:
            async with self.sessions() as session:
                result = await replan(
                    ReplanPlanningRequest(regions=[Region.VOSTOK]),
                    PlanningService(
                        UnitOfWork(session),
                        FakeGeocoder(),
                        storage,
                        AlgorithmService(),
                        FakeMatrixService(),
                    ),
                )
            self.assertEqual(result.status, "success")
            return result.regions[0].plan_summary

        second = await next_east_candidate()
        third = await next_east_candidate()
        self.assertEqual(second.based_on_plan_id, initial_by_region[Region.VOSTOK])
        self.assertEqual(third.based_on_plan_id, initial_by_region[Region.VOSTOK])

        async with self.sessions() as session:
            engineer = (
                await session.scalars(select(Engineer).where(Engineer.region == Region.VOSTOK))
            ).one()
            engineer.is_available = False
            await session.commit()
        async with self.sessions() as session:
            with self.assertRaises(PlanStateChangedError):
                await PlanService(UnitOfWork(session)).approve(second.id)
            await session.rollback()
        async with self.sessions() as session:
            engineer = (
                await session.scalars(select(Engineer).where(Engineer.region == Region.VOSTOK))
            ).one()
            engineer.is_available = True
            await session.commit()

        async with self.sessions() as session:
            await PlanService(UnitOfWork(session)).approve(second.id)
        async with self.sessions() as session:
            plans = PlanService(UnitOfWork(session))
            current = await plans.get_current(Region.VOSTOK, now.date())
            rejected_sibling = await plans.get_by_id(third.id)
        self.assertEqual(current.id, second.id)
        self.assertEqual(rejected_sibling.approval_status, ApprovalStatus.REJECTED)

        fourth = await next_east_candidate()
        self.assertEqual(fourth.based_on_plan_id, second.id)
