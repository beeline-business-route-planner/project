"""G02 against a fresh migrated PostgreSQL database named g02_test_* on localhost.

Set G02_TEST_DATABASE_URL explicitly. Regular unit-test runs skip this suite.
Routing, geocoding and S3 are replaced with deterministic in-process fakes.
"""

import asyncio
import os
import unittest
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from src.api.exc.plans import (
    InitialPlanExpiredError,
    PlanNotFoundError,
    PlanNotPendingError,
    PlanStateChangedError,
)
from src.api.planning.dto import PlanningUploadFile
from src.api.planning.router import import_initial_planning_data
from src.api.planning.service import PlanningService
from src.api.plans.router import approve_plan, get_current_plan, get_plan, reject_plan
from src.api.plans.service import PlanService
from src.core.algorithm import AlgorithmService
from src.core.db.enums import ApprovalStatus, Region
from src.core.db.models import BaselineResult, DataUpload, Plan, PlanStop, Request
from src.core.db.uow import UnitOfWork
from src.core.dgis import DgisUnavailableError
from src.core.dgis.service import DgisMatrix
from src.core.geocoding.dto import Coordinates

DATABASE_URL = os.environ.get("G02_TEST_DATABASE_URL")
MOSCOW = ZoneInfo("Europe/Moscow")


class FakeGeocoder:
    async def geocode(self, address: str) -> Coordinates:
        return Coordinates(Decimal("55.750000"), Decimal("37.600000"))


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: set[str] = set()
        self.deleted: set[str] = set()

    async def upload_file(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.uploaded.add(key)

    async def delete_file(self, bucket: str, key: str) -> None:
        self.deleted.add(key)


class FakeMatrixService:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def build_matrix(self, points: list, **kwargs: object) -> DgisMatrix:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise DgisUnavailableError("Синтетический сбой маршрутизации")
        indexes = {point.id: index for index, point in enumerate(points)}
        size = len(points)
        return DgisMatrix(
            indexes,
            [[0 if row == col else 5 for col in range(size)] for row in range(size)],
            [
                [Decimal(0) if row == col else Decimal(1) for col in range(size)]
                for row in range(size)
            ],
        )


def workbook(region: str, role: str) -> PlanningUploadFile:
    book = Workbook()
    sheet = book.active
    sheet["A1"] = region
    if role == "requests":
        sheet.append(
            [
                "Заявка",
                "Тип заявки BK",
                "Тип заявки HD",
                "Начало",
                "Окончание",
                "Район",
                "Адрес",
                "Гигабитное подключение",
            ]
        )
        sheet.append(["Адрес офиса", "Офис"])
        now = datetime.now(MOSCOW).replace(tzinfo=None)
        start = max(
            datetime.combine(now.date(), time(10)),
            (now + timedelta(minutes=20)).replace(second=0, microsecond=0),
        )
        sheet.append(
            [
                1,
                "Локальная заявка",
                "Информация",
                start.strftime("%d.%m.%Y %H:%M"),
                datetime.combine(now.date(), time(23, 59)).strftime("%d.%m.%Y %H:%M"),
                "Район",
                "Адрес клиента",
                "Нет",
            ]
        )
    else:
        sheet.append(
            [
                "Инженер",
                "Стартовая точка",
                "Начало смены",
                "Конец смены",
                "Навык 1",
                "Тип транспорта",
            ]
        )
        sheet.append(["Анна", "Старт", "00:00", "23:59", "Локальные работы", "Автомобиль"])
    data = BytesIO()
    book.save(data)
    return PlanningUploadFile(
        filename=f"{region}-{role}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data=data.getvalue(),
    )


def pair(region: str) -> list[PlanningUploadFile]:
    return [workbook(region, "requests"), workbook(region, "engineers")]


@unittest.skipUnless(DATABASE_URL, "G02_TEST_DATABASE_URL is not set")
class InitialEndToEndTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        assert DATABASE_URL is not None
        url = make_url(DATABASE_URL)
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host not in {"127.0.0.1", "localhost"}
            or not (url.database or "").startswith("g02_test_")
        ):
            self.fail("G02 requires a disposable local g02_test_* database")
        self.engine = create_async_engine(
            DATABASE_URL,
            pool_size=3,
            max_overflow=0,
            connect_args={"server_settings": {"timezone": "UTC"}},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.storage = FakeStorage()
        async with self.sessions() as session:
            count = await session.scalar(select(func.count()).select_from(Plan))
            self.assertEqual(count, 0, "G02 database must be freshly migrated and empty")

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def import_files(self, files: list[PlanningUploadFile], fail_matrix_call=None):
        uploads = [UploadFile(file=BytesIO(item.data), filename=item.filename) for item in files]
        async with self.sessions() as session:
            service = PlanningService(
                UnitOfWork(session),
                FakeGeocoder(),
                self.storage,
                AlgorithmService(),
                FakeMatrixService(fail_matrix_call),
            )
            return await import_initial_planning_data(service, uploads)

    async def detail(self, plan_id):
        async with self.sessions() as session:
            return await get_plan(PlanService(UnitOfWork(session)), plan_id)

    async def current(self, region, planning_date):
        async with self.sessions() as session:
            return await get_current_plan(PlanService(UnitOfWork(session)), region, planning_date)

    async def approve(self, plan_id):
        async with self.sessions() as session:
            return await approve_plan(PlanService(UnitOfWork(session)), plan_id)

    async def reject(self, plan_id):
        async with self.sessions() as session:
            return await reject_plan(PlanService(UnitOfWork(session)), plan_id)

    async def test_initial_lifecycle_and_partial_success(self) -> None:
        now = datetime.now(MOSCOW)
        if now.hour == 23:
            self.skipTest("Для initial с утверждением нужен остаток рабочего дня")
        today = now.date()

        result = await self.import_files(
            pair("Восток") + pair("Югоцентр") + pair("Юго-восток"), fail_matrix_call=2
        )
        self.assertEqual(result.status, "partial_success")
        self.assertEqual(
            [entry.status for entry in result.regions], ["success", "error", "success"]
        )
        self.assertEqual(result.regions[1].error.code, "routing_unavailable")
        self.assertEqual(result.regions[0].plan_summary.created_at.tzinfo, UTC)
        self.assertEqual(result.regions[0].plan_summary.approval_deadline.tzinfo, UTC)
        east_first = result.regions[0].plan_summary.id
        center_first = result.regions[2].plan_summary.id
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(Plan)), 2)
            self.assertEqual(
                await session.scalar(select(func.count()).select_from(BaselineResult)), 2
            )
            self.assertEqual(await session.scalar(select(func.count()).select_from(DataUpload)), 2)
            self.assertEqual(await session.scalar(select(func.count()).select_from(PlanStop)), 2)
        self.assertEqual(len(self.storage.uploaded), 6)
        self.assertEqual(len(self.storage.deleted), 2)
        self.assertTrue(self.storage.deleted <= self.storage.uploaded)
        self.assertEqual(len(self.storage.uploaded - self.storage.deleted), 4)

        pending = await self.detail(east_first)
        self.assertEqual(pending.approval_status, ApprovalStatus.PENDING)
        self.assertEqual(pending.created_at.tzinfo, UTC)
        self.assertEqual(pending.approval_deadline.tzinfo, UTC)
        self.assertIsNone(pending.calculation_cutoff_at.tzinfo)
        self.assertTrue(pending.can_approve)
        self.assertIsNone(pending.diff)
        self.assertIsNotNone(pending.baseline_metrics)
        self.assertEqual(pending.baseline_metrics.algorithm_version, "baseline-v2")
        self.assertEqual(pending.baseline_metrics.assigned_requests_count, 1)
        self.assertEqual(pending.metrics.assigned_requests_count, 1)
        self.assertEqual(
            pending.baseline_metrics.average_workload_with_travel,
            pending.metrics.average_workload_with_travel,
        )
        self.assertEqual(
            pending.baseline_metrics.average_workload_without_travel,
            pending.metrics.average_workload_without_travel,
        )
        self.assertEqual(pending.planning_date, today)
        self.assertGreater(pending.calculation_cutoff_at.time(), time(0))
        stops = [stop for engineer in pending.engineers for stop in engineer.stops]
        self.assertEqual(len(stops), 1)
        self.assertGreaterEqual(stops[0].planned_start, pending.calculation_cutoff_at)

        repeat = await self.import_files(pair("Восток"))
        self.assertEqual(repeat.status, "success")
        east_second = repeat.regions[0].plan_summary.id
        self.assertNotEqual(east_second, east_first)
        decision = await self.approve(east_second)
        self.assertEqual(decision.approval_status, ApprovalStatus.APPROVED)
        self.assertEqual(decision.approved_at.tzinfo, UTC)
        self.assertEqual((await self.detail(east_first)).approval_status, ApprovalStatus.REJECTED)
        with self.assertRaises(PlanNotPendingError):
            await self.approve(east_first)
        current = await self.current(Region.VOSTOK, today)
        self.assertEqual(current.id, east_second)
        self.assertTrue(current.is_current)
        self.assertEqual(current.baseline_metrics.algorithm_version, "baseline-v2")
        with self.assertRaises(PlanNotFoundError):
            await self.current(Region.VOSTOK, today - timedelta(days=1))
        with self.assertRaises(PlanNotFoundError):
            await self.current(Region.YUGOTSENTR, today)
        forbidden = await self.import_files(pair("Восток"))
        self.assertEqual(forbidden.regions[0].error.code, "initial_already_approved")

        rejected = await self.reject(center_first)
        self.assertEqual(rejected.approval_status, ApprovalStatus.REJECTED)
        with self.assertRaises(PlanNotFoundError):
            await self.current(Region.YUGOTSENTR, today)

        center_a = await self.import_files(pair("Югоцентр"))
        center_b = await self.import_files(pair("Югоцентр"))
        center_ids = [center_a.regions[0].plan_summary.id, center_b.regions[0].plan_summary.id]
        outcomes = await asyncio.gather(
            *(self.approve(plan_id) for plan_id in center_ids), return_exceptions=True
        )
        successes = [value for value in outcomes if not isinstance(value, BaseException)]
        failures = [value for value in outcomes if isinstance(value, BaseException)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], PlanNotPendingError)
        winner = successes[0]
        self.assertEqual((await self.current(Region.YUGOTSENTR, today)).id, winner.id)
        loser = center_ids[0] if winner.id == center_ids[1] else center_ids[1]
        self.assertEqual((await self.detail(loser)).approval_status, ApprovalStatus.REJECTED)
        async with self.sessions() as session:
            approved_count = await session.scalar(
                select(func.count())
                .select_from(Plan)
                .where(
                    Plan.region == Region.YUGOTSENTR,
                    Plan.planning_date == today,
                    Plan.approval_status == ApprovalStatus.APPROVED,
                )
            )
            self.assertEqual(approved_count, 1)

        southeast = await self.import_files(pair("Юго-восток"))
        expired_id = southeast.regions[0].plan_summary.id
        async with self.sessions() as session:
            plan = await UnitOfWork(session).plans.get_by_id(expired_id)
            plan.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=11)
            await session.commit()
        with self.assertRaises(InitialPlanExpiredError):
            await self.approve(expired_id)
        self.assertEqual((await self.detail(expired_id)).approval_status, ApprovalStatus.PENDING)

        async with self.sessions() as long_session:
            # PostgreSQL now() остаётся временем начала транзакции даже после расчёта.
            await long_session.scalar(select(func.now()))
            await asyncio.sleep(0.01)
            changed = await self.import_files(pair("Юго-восток"))
            changed_id = changed.regions[0].plan_summary.id
            plan = await UnitOfWork(long_session).plans.get_by_id(changed_id)
            request = await long_session.scalar(
                select(Request).where(Request.upload_id == plan.upload_id)
            )
            request.address = "Изменённый адрес"
            await long_session.commit()
        async with self.sessions() as session:
            updated_request = await session.get(Request, request.id)
            self.assertGreater(updated_request.updated_at, plan.created_at)
        with self.assertRaises(PlanStateChangedError):
            await self.approve(changed_id)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(Plan)), 7)
            self.assertEqual(
                await session.scalar(select(func.count()).select_from(BaselineResult)), 7
            )

        # T01 migration kept older approved initial plans without baseline rows.
        async with self.sessions() as session:
            baseline = await session.scalar(
                select(BaselineResult).where(BaselineResult.initial_plan_id == east_second)
            )
            self.assertIsNotNone(baseline)
            await session.delete(baseline)
            await session.commit()
        self.assertIsNone((await self.detail(east_second)).baseline_metrics)
        self.assertIsNone((await self.current(Region.VOSTOK, today)).baseline_metrics)
