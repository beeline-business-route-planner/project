"""Malformed workbook sets fail at HTTP level before any region is processed."""

import unittest
from unittest.mock import AsyncMock, patch

import httpx
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from src.api.exc.base import register_all
from src.api.planning.dto import InitialPlanningResult, PlanningUploadFile
from src.api.planning.router import router
from src.api.planning.service import PlanningService
from src.core.db.enums import DistributionMode, PlanStrategy

from tests.support.planning import pair


class PlanningServiceProvider(Provider):
    def __init__(self, service: PlanningService) -> None:
        super().__init__()
        self.service = service

    @provide(scope=Scope.REQUEST)
    def planning_service(self) -> PlanningService:
        return self.service


class InitialUploadHttpContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_initial_defaults_to_balanced_mode_and_lns_strategy(self) -> None:
        service = PlanningService(object(), object(), object(), object(), object())
        container = make_async_container(PlanningServiceProvider(service))
        app = FastAPI()
        setup_dishka(container=container, app=app)
        app.include_router(router, prefix="/api")
        register_all(app)
        try:
            with patch.object(
                service,
                "import_initial_data",
                new_callable=AsyncMock,
                return_value=InitialPlanningResult(status="error", regions=()),
            ) as imported:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test.local"
                ) as client:
                    response = await client.post(
                        "/api/planning/initial",
                        files=[
                            ("files", (item.filename, item.data, item.content_type))
                            for item in pair("Восток")
                        ],
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    imported.await_args.args[1:],
                    (DistributionMode.BALANCED, PlanStrategy.LNS),
                )
        finally:
            await container.close()

    async def assert_rejected(self, files: list[PlanningUploadFile]) -> None:
        service = PlanningService(object(), object(), object(), object(), object())
        container = make_async_container(PlanningServiceProvider(service))
        app = FastAPI()
        setup_dishka(container=container, app=app)
        app.include_router(router, prefix="/api")
        register_all(app)
        try:
            with patch.object(service, "_run_region", new_callable=AsyncMock) as run_region:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test.local"
                ) as client:
                    response = await client.post(
                        "/api/planning/initial",
                        files=[
                            ("files", (item.filename, item.data, item.content_type))
                            for item in files
                        ],
                    )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["detail"],
                    "Для каждого округа нужна ровно одна таблица заявок и одна таблица инженеров",
                )
                run_region.assert_not_awaited()
        finally:
            await container.close()

    async def test_odd_number_of_workbooks_returns_422(self) -> None:
        await self.assert_rejected(pair("Восток")[:1])

    async def test_books_from_different_regions_return_422(self) -> None:
        await self.assert_rejected([pair("Восток")[0], pair("Югоцентр")[1]])

    async def test_duplicate_pair_returns_422(self) -> None:
        files = pair("Восток")
        await self.assert_rejected(files + files)

    async def test_valid_region_is_not_committed_before_invalid_pair_is_found(self) -> None:
        await self.assert_rejected(pair("Восток") + [pair("Югоцентр")[0]] * 2)
