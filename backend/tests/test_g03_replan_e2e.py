import os
import unittest
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from src.api.exc.plans import PlanStateChangedError, PlanStopAlreadyStartedError
from src.api.planning.router import import_initial_planning_data, replan
from src.api.planning.schemas import ReplanPlanningRequest, ReplanPlanSummaryResponse
from src.api.planning.service import PlanningService
from src.api.plans.export import PlanXlsxExporter
from src.api.plans.service import PlanService
from src.core.algorithm import AlgorithmService
from src.core.db.enums import ApprovalStatus, Region, ReplanningEventType, RequestStatus
from src.core.db.models import Engineer, Plan, PlanStop, ReplanningEvent, Request
from src.core.db.uow import UnitOfWork
from tests.test_g02_initial_e2e import FakeGeocoder, FakeMatrixService, FakeStorage, pair

DATABASE_URL = os.environ.get("G03_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "G03_TEST_DATABASE_URL is not set")
class ReplanEndToEndTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        assert DATABASE_URL is not None
        url = make_url(DATABASE_URL)
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host not in {"127.0.0.1", "localhost"}
            or not (url.database or "").startswith("g03_test_")
        ):
            self.fail("G03 requires a disposable local g03_test_* database")
        self.engine = create_async_engine(
            DATABASE_URL, connect_args={"server_settings": {"timezone": "UTC"}}
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.storage = FakeStorage()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _replan_one(self) -> ReplanPlanSummaryResponse:
        async with self.sessions() as session:
            result = await replan(
                ReplanPlanningRequest(regions=[Region.VOSTOK]),
                PlanningService(
                    UnitOfWork(session),
                    FakeGeocoder(),
                    self.storage,
                    AlgorithmService(),
                    FakeMatrixService(),
                ),
            )
        self.assertEqual(result.status, "success")
        summary = result.regions[0].plan_summary
        assert summary is not None
        return summary

    async def test_diff_late_decisions_locked_history_and_export(self) -> None:
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        if now.hour == 23:
            self.skipTest("Initial approval needs enough of the working day left")
        files = pair("Восток")
        uploads = [UploadFile(file=BytesIO(item.data), filename=item.filename) for item in files]
        async with self.sessions() as session:
            initial = await import_initial_planning_data(
                PlanningService(
                    UnitOfWork(session),
                    FakeGeocoder(),
                    self.storage,
                    AlgorithmService(),
                    FakeMatrixService(),
                ),
                uploads,
            )
        self.assertEqual(initial.status, "success")
        base_id = initial.regions[0].plan_summary.id
        async with self.sessions() as session:
            await PlanService(UnitOfWork(session)).approve(base_id)

        first = await self._replan_one()
        sibling = await self._replan_one()
        self.assertEqual(first.based_on_plan_id, base_id)
        self.assertEqual(sibling.based_on_plan_id, base_id)
        async with self.sessions() as session:
            await PlanService(UnitOfWork(session)).approve(first.id)
        async with self.sessions() as session:
            plans = PlanService(UnitOfWork(session))
            rejected = await plans.get_by_id(sibling.id)
            current = await plans.get_current(Region.VOSTOK, now.date())
        self.assertEqual(rejected.approval_status, ApprovalStatus.REJECTED)
        self.assertEqual(rejected.diff.base_plan_id, base_id)
        self.assertEqual(current.id, first.id)

        stale_request = await self._replan_one()
        self.assertEqual(stale_request.based_on_plan_id, first.id)
        async with self.sessions() as session:
            request = (await session.scalars(select(Request))).one()
            request.status = RequestStatus.SENT
            await session.commit()
        async with self.sessions() as session:
            with self.assertRaises(PlanStateChangedError):
                await PlanService(UnitOfWork(session)).approve(stale_request.id)
            await session.rollback()

        async with self.sessions() as session:
            request = (await session.scalars(select(Request))).one()
            request.status = RequestStatus.CANCELLED
            await session.commit()
        removed = await self._replan_one()
        async with self.sessions() as session:
            removed_stops = (
                await session.scalars(select(PlanStop).where(PlanStop.plan_id == removed.id))
            ).all()
            self.assertEqual(removed_stops, [])
            request = (await session.scalars(select(Request))).one()
            request.status = RequestStatus.SENT
            await session.commit()
        async with self.sessions() as session:
            with self.assertRaises(PlanStateChangedError):
                await PlanService(UnitOfWork(session)).approve(removed.id)
            await session.rollback()

        mutable = await self._replan_one()
        async with self.sessions() as session:
            candidate_stop = (
                await session.scalars(select(PlanStop).where(PlanStop.plan_id == mutable.id))
            ).one()
            base_stop = (
                await session.scalars(select(PlanStop).where(PlanStop.plan_id == first.id))
            ).one()
            future_now = max(candidate_stop.planned_start, base_stop.planned_start) + timedelta(
                minutes=1
            )
            self.assertEqual(future_now.date(), now.date())
            candidate = await session.get(Plan, mutable.id)
            assert candidate is not None
            with self.assertRaises(PlanStopAlreadyStartedError):
                await PlanService(UnitOfWork(session))._validate_approval(
                    candidate, future_now, datetime.now(UTC).replace(tzinfo=None)
                )
            await session.rollback()
        async with self.sessions() as session:
            await PlanService(UnitOfWork(session)).reject(mutable.id)

        async with self.sessions() as session:
            request = (await session.scalars(select(Request))).one()
            request.status = RequestStatus.ON_THE_WAY
            await session.commit()
        locked = await self._replan_one()
        async with self.sessions() as session:
            locked_stop = (
                await session.scalars(select(PlanStop).where(PlanStop.plan_id == locked.id))
            ).one()
            base_stop = (
                await session.scalars(select(PlanStop).where(PlanStop.plan_id == first.id))
            ).one()
            self.assertTrue(locked_stop.is_locked)
            self.assertEqual(
                (
                    locked_stop.engineer_id,
                    locked_stop.sequence_number,
                    locked_stop.planned_arrival,
                    locked_stop.planned_start,
                    locked_stop.planned_finish,
                    locked_stop.travel_minutes,
                    locked_stop.distance_km,
                ),
                (
                    base_stop.engineer_id,
                    base_stop.sequence_number,
                    base_stop.planned_arrival,
                    base_stop.planned_start,
                    base_stop.planned_finish,
                    base_stop.travel_minutes,
                    base_stop.distance_km,
                ),
            )
            await PlanService(UnitOfWork(session)).approve(locked.id)

        async with self.sessions() as session:
            snapshot = await PlanService(UnitOfWork(session)).get_snapshot_by_id(locked.id)
        self.assertGreater(len(PlanXlsxExporter.build(snapshot)), 0)

        after_event = await self._replan_one()
        async with self.sessions() as session:
            engineer = (await session.scalars(select(Engineer))).one()
            event = ReplanningEvent(
                region=Region.VOSTOK,
                planning_date=now.date(),
                event_type=ReplanningEventType.ENGINEER_UNAVAILABLE,
                approval_status=ApprovalStatus.APPROVED,
                occurred_at=datetime.now(UTC).replace(tzinfo=None),
                engineer_id=engineer.id,
                approved_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(event)
            await session.commit()
        async with self.sessions() as session:
            with self.assertRaises(PlanStateChangedError):
                await PlanService(UnitOfWork(session)).approve(after_event.id)
            await session.rollback()
