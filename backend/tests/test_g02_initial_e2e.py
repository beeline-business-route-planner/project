"""Opt-in G02: run against a fresh, migrated, disposable local PostgreSQL database.

Set G02_TEST_DATABASE_URL to a localhost URL with a database named g02_test_*.
The normal unit-test run skips this suite; it never touches project data or external APIs.
"""

import asyncio
import os
import unittest
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

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
from src.api.planning.schemas import InitialPlanningResponse, InitialPlanSummaryResponse
from src.api.planning.service import PlanningService
from src.api.plans.schemas import PlanDetailResponse, PlanSummaryResponse
from src.api.plans.service import PlanService
from src.core.algorithm import AlgorithmService
from src.core.db.enums import ApprovalStatus, Region
from src.core.db.models import BaselineResult, DataUpload, Plan, Request
from src.core.db.uow import UnitOfWork
from src.core.dgis.service import DgisMatrix
from src.core.geocoding.dto import Coordinates
from src.core.geocoding.exc import AddressNotFoundError

DATABASE_URL = os.environ.get("G02_TEST_DATABASE_URL")


class FakeGeocoder:
    async def geocode(self, address: str) -> Coordinates:
        if address == "Неверный адрес":
            raise AddressNotFoundError(address)
        return Coordinates(Decimal("55.750000"), Decimal("37.600000"))


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: list[str] = []
        self.deleted: list[str] = []

    async def upload_file(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.uploaded.append(key)

    async def delete_file(self, bucket: str, key: str) -> None:
        self.deleted.append(key)


class FakeMatrixService:
    async def build_matrix(self, points: list, **kwargs: object) -> DgisMatrix:
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


def workbook(region: str, role: str, *, invalid_address: bool = False) -> PlanningUploadFile:
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
        day = datetime.now(ZoneInfo("Europe/Moscow")).date()
        sheet.append(
            [
                1,
                "Локальная заявка",
                "Информация",
                datetime.combine(day, time(16)).strftime("%d.%m.%Y %H:%M"),
                datetime.combine(day, time(21)).strftime("%d.%m.%Y %H:%M"),
                "Район",
                "Неверный адрес" if invalid_address else "Адрес клиента",
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
        sheet.append(["Анна", "Старт", "10:00", "22:00", "Локальные работы", "Автомобиль"])
    data = BytesIO()
    book.save(data)
    return PlanningUploadFile(
        filename=f"{region}-{role}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data=data.getvalue(),
    )


def pair(region: str, *, invalid_address: bool = False) -> list[PlanningUploadFile]:
    return [
        workbook(region, "requests", invalid_address=invalid_address),
        workbook(region, "engineers"),
    ]


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
            self.fail("G02 integration tests require a disposable local g02_test_* database")
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
            self.assertEqual(count, 0, "G02 test database must be freshly migrated and empty")

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def import_files(self, files: list[PlanningUploadFile]):
        async with self.sessions() as session:
            return await PlanningService(
                UnitOfWork(session),
                FakeGeocoder(),
                self.storage,
                AlgorithmService(),
                FakeMatrixService(),
            ).import_initial_data(files)

    async def plan_detail(self, plan_id):
        async with self.sessions() as session:
            return await PlanService(UnitOfWork(session)).get_by_id(plan_id)

    async def approve(self, plan_id):
        async with self.sessions() as session:
            return await PlanService(UnitOfWork(session)).approve(plan_id)

    async def test_initial_lifecycle_and_partial_success(self) -> None:
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        self.assertGreaterEqual(datetime.now(ZoneInfo("Europe/Moscow")).hour, 10)

        result = await self.import_files(
            pair("Восток") + pair("Югоцентр") + pair("Юго-восток", invalid_address=True)
        )
        self.assertEqual(result.status, "partial_success")
        self.assertEqual(
            [entry.status for entry in result.regions], ["success", "error", "success"]
        )
        self.assertEqual(result.regions[1].error_code, "address_not_found")
        InitialPlanningResponse.model_validate(
            {
                "status": result.status,
                "regions": [
                    {
                        "region": entry.region,
                        "status": entry.status,
                        "plan_summary": (
                            InitialPlanSummaryResponse.model_validate(
                                entry.plan_summary, from_attributes=True
                            )
                            if entry.plan_summary
                            else None
                        ),
                        "error": (
                            {"code": entry.error_code, "detail": entry.error_detail}
                            if entry.error_code
                            else None
                        ),
                    }
                    for entry in result.regions
                ],
            }
        )
        east_first = result.regions[0].plan_summary.id
        center = result.regions[2].plan_summary.id
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(Plan)), 2)
            self.assertEqual(
                await session.scalar(select(func.count()).select_from(BaselineResult)), 2
            )
            self.assertEqual(await session.scalar(select(func.count()).select_from(DataUpload)), 2)

        first_detail = await self.plan_detail(east_first)
        self.assertEqual(first_detail.approval_status, ApprovalStatus.PENDING)
        self.assertIsNone(first_detail.diff)
        self.assertIsNotNone(first_detail.baseline_metrics)
        self.assertEqual(first_detail.baseline_metrics.algorithm_version, "baseline-v2")
        self.assertEqual(first_detail.planning_date, today)
        self.assertGreater(first_detail.calculation_cutoff_at.time(), time(10))
        self.assertTrue(
            all(
                stop.planned_start >= first_detail.calculation_cutoff_at
                for engineer in first_detail.engineers
                for stop in engineer.stops
            )
        )
        PlanDetailResponse.model_validate(first_detail)

        repeat = await self.import_files(pair("Восток"))
        self.assertEqual(repeat.status, "success")
        east_second = repeat.regions[0].plan_summary.id
        self.assertNotEqual(east_second, east_first)
        outcomes = await asyncio.gather(
            self.approve(east_second), self.approve(east_first), return_exceptions=True
        )
        successes = [value for value in outcomes if not isinstance(value, BaseException)]
        failures = [value for value in outcomes if isinstance(value, BaseException)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], PlanNotPendingError)
        winner = successes[0]
        PlanSummaryResponse.model_validate(winner)
        loser = east_first if winner.id == east_second else east_second
        self.assertEqual((await self.plan_detail(loser)).approval_status, ApprovalStatus.REJECTED)
        async with self.sessions() as session:
            service = PlanService(UnitOfWork(session))
            current = await service.get_current(Region.VOSTOK, today)
            self.assertEqual(current.id, winner.id)
            self.assertTrue(current.is_current)
            self.assertEqual(current.baseline_metrics.algorithm_version, "baseline-v2")
            with self.assertRaises(PlanNotFoundError):
                await service.get_current(Region.VOSTOK, today - timedelta(days=1))
            with self.assertRaises(PlanNotFoundError):
                await service.get_current(Region.YUGOTSENTR, today)

        forbidden = await self.import_files(pair("Восток"))
        self.assertEqual(forbidden.regions[0].error_code, "initial_already_approved")
        async with self.sessions() as session:
            service = PlanService(UnitOfWork(session))
            rejected = await service.reject(center)
            self.assertEqual(rejected.approval_status, ApprovalStatus.REJECTED)
            with self.assertRaises(PlanNotFoundError):
                await service.get_current(Region.YUGOTSENTR, today)
        center_repeat = await self.import_files(pair("Югоцентр"))
        self.assertEqual(center_repeat.status, "success")
        expired_id = center_repeat.regions[0].plan_summary.id
        async with self.sessions() as session:
            plan = await UnitOfWork(session).plans.get_by_id(expired_id)
            plan.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=11)
            await session.commit()
        async with self.sessions() as session:
            with self.assertRaises(InitialPlanExpiredError):
                await PlanService(UnitOfWork(session)).approve(expired_id)
        self.assertEqual(
            (await self.plan_detail(expired_id)).approval_status, ApprovalStatus.PENDING
        )

        changed = await self.import_files(pair("Югоцентр"))
        self.assertEqual(changed.status, "success")
        changed_id = changed.regions[0].plan_summary.id
        async with self.sessions() as session:
            plan = await UnitOfWork(session).plans.get_by_id(changed_id)
            request = await session.scalar(
                select(Request).where(Request.upload_id == plan.upload_id)
            )
            request.address = "Изменённый адрес"
            await session.commit()
        async with self.sessions() as session:
            with self.assertRaises(PlanStateChangedError):
                await PlanService(UnitOfWork(session)).approve(changed_id)
