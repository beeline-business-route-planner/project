import unittest
import uuid
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from openpyxl import Workbook
from src.api.exc.planning import PlanningFileValidationError
from src.api.planning.dto import ParsedWorkbook, PlanningRegionResult, PlanningUploadFile
from src.api.planning.parser import PlanningWorkbookParser
from src.api.planning.service import PlanningService
from src.core.db.enums import Region
from src.core.dgis import DgisUnavailableError
from src.core.s3 import S3UnavailableError


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
        self.service._delete_uploaded_objects = AsyncMock(return_value=True)
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

    def test_workbook_role_and_region_ignore_filename(self) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet["A1"] = "Восток"
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
        sheet.append(["Анна", "Москва", "10:00", "22:00", "Локальные работы", "Автомобиль"])
        content = BytesIO()
        workbook.save(content)
        source = PlanningUploadFile(
            filename="Контрольное распределение.bin",
            content_type="application/octet-stream",
            data=content.getvalue(),
        )

        self.assertEqual(PlanningWorkbookParser.identify_region(source), Region.VOSTOK)
        parsed = PlanningWorkbookParser.parse(source)
        self.assertEqual(parsed.role, "engineers")
        self.assertEqual(parsed.engineers[0].name, "Анна")

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
        events = []

        async def prepare(*args):
            events.append("geocode")
            return {}

        async def persist(*args):
            events.append("persist")
            return uuid.uuid7(), [], []

        async def calculate(*args):
            events.append("calculate")
            return plan_id

        self.service._prepare_region.side_effect = prepare
        self.service._persist_region = AsyncMock(side_effect=persist)
        self.service._calculate_and_persist_initial = AsyncMock(side_effect=calculate)
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
        with patch("src.api.planning.service.datetime") as clock:

            def now(tz):
                events.append("cutoff")
                return datetime(2026, 9, 25, 11)

            clock.now.side_effect = now
            result = await self.service._run_region(
                Region.VOSTOK, self.request_book, self.engineer_book
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.plan_summary.id, plan_id)
        self.assertEqual(events, ["geocode", "persist", "cutoff", "calculate"])
        self.assertEqual(self.uow.flush.await_count, 2)
        self.uow.commit.assert_awaited_once()
        self.uow.rollback.assert_not_awaited()
        self.service._delete_uploaded_objects.assert_not_awaited()
        calculation_args = self.service._calculate_and_persist_initial.await_args.args
        self.assertEqual(calculation_args[2], date(2026, 9, 25))
        self.assertEqual(calculation_args[3], datetime(2026, 9, 25, 11))

    async def test_cutoff_and_same_input_reach_plan_and_baseline(self) -> None:
        cutoff = datetime(2026, 9, 25, 11)
        plan_id = uuid.uuid7()
        metrics = SimpleNamespace(
            total_mileage_km=Decimal("2.50"),
            engineers_used_count=1,
            assigned_requests_count=1,
            unassigned_requests_count=0,
            average_utilization_with_travel=Decimal("0.50"),
            average_utilization_without_travel=Decimal("0.40"),
        )
        calculated = SimpleNamespace(
            region=Region.VOSTOK,
            planning_date=date(2026, 9, 25),
            calculation_cutoff_at=cutoff,
            metrics=metrics,
            routes=(),
            unassigned=(),
        )
        planning_input = object()
        algorithm = SimpleNamespace(
            prepare_initial=MagicMock(return_value=SimpleNamespace(points=(), matrix_requests=())),
            build_initial_input=MagicMock(return_value=planning_input),
            plan_initial=MagicMock(return_value=calculated),
            plan_baseline=MagicMock(
                return_value=SimpleNamespace(metrics=metrics, algorithm_version="baseline-v2")
            ),
        )
        self.service._algorithm = algorithm
        self.uow.plans.create = MagicMock(return_value=plan_id)
        self.uow.baseline_results = SimpleNamespace(create=MagicMock())
        self.uow.plan_engineer_states = SimpleNamespace(add_many=MagicMock())
        self.uow.plan_stops = SimpleNamespace(add_many=MagicMock())
        self.uow.plan_unassigned_requests = SimpleNamespace(add_many=MagicMock())

        result = await self.service._calculate_and_persist_initial(
            uuid.uuid7(), Region.VOSTOK, date(2026, 9, 25), cutoff, [], [], object()
        )

        self.assertEqual(result, plan_id)
        self.assertEqual(algorithm.prepare_initial.call_args.args[0].calculation_cutoff_at, cutoff)
        algorithm.plan_initial.assert_called_once_with(planning_input)
        algorithm.plan_baseline.assert_called_once_with(planning_input)
        self.assertEqual(self.uow.plans.create.call_args.args[0].calculation_cutoff_at, cutoff)
        self.assertEqual(
            self.uow.baseline_results.create.call_args.args[0].initial_plan_id, plan_id
        )
        self.uow.commit.assert_not_awaited()

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

    async def test_failed_region_does_not_block_successful_neighbor(self) -> None:
        files = [
            PlanningUploadFile(filename=name, content_type="xlsx", data=b"xlsx")
            for name in ("east-r", "east-e", "south-r", "south-e")
        ]

        def identify(file):
            return Region.VOSTOK if file.filename.startswith("east") else Region.YUGOTSENTR

        def parse(file):
            region = identify(file)
            role = "requests" if file.filename.endswith("-r") else "engineers"
            return self._book(region, role)

        async def persist(region, *args):
            if region == Region.VOSTOK:
                args[-1].append(("uploads", "planning/east/source"))
            return uuid.uuid7(), [], []

        plan_id = uuid.uuid7()
        self.service._persist_region = AsyncMock(side_effect=persist)
        self.service._calculate_and_persist_initial = AsyncMock(
            side_effect=[DgisUnavailableError("routing failed"), plan_id]
        )
        self.plans.get_by_id.return_value = SimpleNamespace(
            id=plan_id,
            region=Region.YUGOTSENTR,
            planning_date=date(2026, 9, 25),
            created_at=datetime(2026, 9, 25, 11),
            assigned_requests_count=1,
            unassigned_requests_count=0,
            engineers_used_count=1,
            total_mileage_km=Decimal("2.50"),
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
        self.assertEqual([item.status for item in result.regions], ["error", "success"])
        self.assertEqual(result.regions[1].plan_summary.id, plan_id)
        self.uow.rollback.assert_awaited_once()
        self.uow.commit.assert_awaited_once()
        self.service._delete_uploaded_objects.assert_awaited_once_with(
            [("uploads", "planning/east/source")]
        )

    async def test_cleanup_still_runs_when_database_rollback_fails(self) -> None:
        self.service._persist_region = AsyncMock(return_value=(uuid.uuid7(), [], []))
        self.service._calculate_and_persist_initial = AsyncMock(
            side_effect=DgisUnavailableError("routing failed")
        )
        self.uow.rollback.side_effect = RuntimeError("database connection lost")

        with self.assertRaises(RuntimeError):
            await self.service._run_region(Region.VOSTOK, self.request_book, self.engineer_book)

        self.service._delete_uploaded_objects.assert_awaited_once()
        self.uow.commit.assert_not_awaited()

    async def test_cleanup_failure_is_visible_in_region_result(self) -> None:
        self.service._persist_region = AsyncMock(return_value=(uuid.uuid7(), [], []))
        self.service._calculate_and_persist_initial = AsyncMock(
            side_effect=DgisUnavailableError("routing failed")
        )
        self.service._delete_uploaded_objects.return_value = False

        result = await self.service._run_region(
            Region.VOSTOK, self.request_book, self.engineer_book
        )

        self.assertEqual(result.error_code, "storage_cleanup_failed")
        self.uow.rollback.assert_awaited_once()

    async def test_cleanup_retries_idempotent_delete(self) -> None:
        storage = SimpleNamespace(delete_file=AsyncMock(side_effect=[S3UnavailableError(), None]))
        self.service._storage = storage
        with patch("src.api.planning.service.asyncio.sleep", new_callable=AsyncMock) as sleep:
            cleaned = await PlanningService._delete_uploaded_objects(
                self.service, [("uploads", "planning/upload-id/input")]
            )

        self.assertTrue(cleaned)
        self.assertEqual(storage.delete_file.await_count, 2)
        sleep.assert_awaited_once()

    async def test_approved_initial_rejects_upload_before_external_calls(self) -> None:
        self.plans.has_approved_initial.return_value = True

        result = await self.service._run_region(
            Region.VOSTOK, self.request_book, self.engineer_book
        )

        self.assertEqual(result.error_code, "initial_already_approved")
        self.uow.rollback.assert_awaited_once()
        self.service._prepare_region.assert_not_awaited()
        self.uow.commit.assert_not_awaited()
