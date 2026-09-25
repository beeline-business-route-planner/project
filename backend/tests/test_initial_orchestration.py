import unittest
import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.api.exc.planning import PlanningFileValidationError
from src.api.planning.dto import ParsedWorkbook, PlanningRegionResult, PlanningUploadFile
from src.api.planning.service import PlanningService
from src.core.db.enums import Region
from src.core.dgis import DgisUnavailableError


class InitialOrchestrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.plans = SimpleNamespace(
            lock_region_day=AsyncMock(),
            has_approved_initial=AsyncMock(return_value=False),
            get_by_id=AsyncMock(),
        )
        self.uow = SimpleNamespace(
            plans=self.plans,
            flush=AsyncMock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        self.service = PlanningService(self.uow, object(), object(), object(), object())
        self.service._prepare_region = AsyncMock(return_value={})
        self.service._delete_uploaded_objects = AsyncMock()
        self.request_book = self._book(Region.VOSTOK, "requests")
        self.engineer_book = self._book(Region.VOSTOK, "engineers")

    @staticmethod
    def _book(region: Region, role: str) -> ParsedWorkbook:
        requests = (
            (SimpleNamespace(external_id=1, window_start=datetime(2026, 9, 25, 10)),)
            if role == "requests"
            else ()
        )
        return ParsedWorkbook(
            source=PlanningUploadFile(filename="input.xlsx", content_type="xlsx", data=b"xlsx"),
            region=region,
            role=role,
            office_address="office" if role == "requests" else None,
            requests=requests,
            engineers=(),
        )

    async def test_invalid_excel_isolated_to_its_region(self) -> None:
        files = [
            PlanningUploadFile(filename=name, content_type="xlsx", data=b"xlsx")
            for name in ("bad-r.xlsx", "bad-e.xlsx", "good-r.xlsx", "good-e.xlsx")
        ]

        def identify(file):
            return Region.VOSTOK if file.filename.startswith("bad") else Region.YUGOTSENTR

        def parse(file):
            if file.filename.startswith("bad"):
                raise PlanningFileValidationError
            role = "requests" if file.filename.endswith("r.xlsx") else "engineers"
            return self._book(Region.YUGOTSENTR, role)

        self.service._run_region = AsyncMock(
            return_value=PlanningRegionResult(region=Region.YUGOTSENTR, status="success")
        )
        with (
            patch(
                "src.api.planning.service.PlanningWorkbookParser.identify_region",
                side_effect=identify,
            ),
            patch("src.api.planning.service.PlanningWorkbookParser.parse", side_effect=parse),
        ):
            result = await self.service.import_initial_data(files)

        self.assertEqual(result.status, "partial_success")
        self.assertEqual(result.regions[0].error_code, "invalid_file")
        self.assertEqual(result.regions[1].status, "success")
        self.service._run_region.assert_awaited_once()

    async def test_success_commits_after_calculation_with_one_cutoff(self) -> None:
        plan_id = uuid.uuid7()
        self.service._persist_region = AsyncMock(return_value=(uuid.uuid7(), [], []))
        self.service._calculate_and_persist_initial = AsyncMock(return_value=plan_id)
        self.plans.get_by_id.return_value = SimpleNamespace(
            id=plan_id,
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 25),
            created_at=datetime(2026, 9, 25, 11),
            assigned_requests_count=1,
            unassigned_requests_count=0,
            engineers_used_count=1,
            total_mileage_km=Decimal("2.50"),
        )

        result = await self.service._run_region(
            Region.VOSTOK, self.request_book, self.engineer_book
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.plan_summary.id, plan_id)
        self.assertEqual(self.uow.flush.await_count, 2)
        self.uow.commit.assert_awaited_once()
        self.uow.rollback.assert_not_awaited()
        self.service._delete_uploaded_objects.assert_not_awaited()
        calculation_args = self.service._calculate_and_persist_initial.await_args.args
        self.assertEqual(calculation_args[2], date(2026, 9, 25))
        self.assertEqual(calculation_args[3].tzinfo, None)

    async def test_routing_failure_rolls_back_and_cleans_only_region_files(self) -> None:
        objects = [("uploads", "planning/object")]

        async def persist(*args):
            args[-1].extend(objects)
            return uuid.uuid7(), [], []

        self.service._persist_region = AsyncMock(side_effect=persist)
        self.service._calculate_and_persist_initial = AsyncMock(
            side_effect=DgisUnavailableError("routing failed")
        )

        result = await self.service._run_region(
            Region.VOSTOK, self.request_book, self.engineer_book
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "routing_unavailable")
        self.uow.rollback.assert_awaited_once()
        self.uow.commit.assert_not_awaited()
        self.service._delete_uploaded_objects.assert_awaited_once_with(objects)

    async def test_approved_initial_rejects_upload_before_external_calls(self) -> None:
        self.plans.has_approved_initial.return_value = True

        result = await self.service._run_region(
            Region.VOSTOK, self.request_book, self.engineer_book
        )

        self.assertEqual(result.error_code, "initial_already_approved")
        self.uow.rollback.assert_awaited_once()
        self.service._prepare_region.assert_not_awaited()
        self.uow.commit.assert_not_awaited()
