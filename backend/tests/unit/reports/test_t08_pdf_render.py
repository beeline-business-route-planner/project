"""T08: рендер PDF из готового snapshot без БД — оформление, графики и крайние случаи."""

import re
import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.api.reports.dto import (
    DailyReportSnapshot,
    RegionReportSnapshot,
    ReportBaseline,
    ReportEngineer,
    ReportEvent,
    ReportMetrics,
    ReportPlanChange,
    ReportPlanVersion,
    ReportStop,
    ReportUnassigned,
)
from src.api.reports.pdf import DailyPdfRenderer
from src.api.reports.pdf_components import fmt_duration, fmt_number, fmt_signed
from src.core.db.enums import PlanKind, Region, ReplanningEventType, UnassignedReason

DAY = date(2026, 9, 29)
SHIFT_START = datetime(2026, 9, 29, 10)


def stop(sequence: int, start: datetime, work: int = 45, travel: int = 20) -> ReportStop:
    return ReportStop(
        external_id=1000 + sequence,
        address=f"Москва, ул. Люблинская, д. {sequence}",
        sequence_number=sequence,
        planned_arrival=start,
        planned_start=start,
        planned_finish=start + timedelta(minutes=work),
        work_minutes=work,
        travel_minutes=travel,
        distance_km=Decimal("7.25"),
        is_locked=sequence == 1,
    )


def engineer(name: str, stops: tuple[ReportStop, ...], available: bool = True) -> ReportEngineer:
    work = sum(item.work_minutes for item in stops)
    travel = sum(item.travel_minutes for item in stops)
    return ReportEngineer(
        id=uuid.uuid4(),
        name=name,
        shift_start=SHIFT_START,
        shift_end=SHIFT_START + timedelta(hours=12),
        is_available=available,
        work_minutes=work,
        travel_minutes=travel,
        mileage_km=Decimal("7.25") * len(stops),
        utilization_with_travel=Decimal(round((work + travel) / 7.2, 2)),
        utilization_without_travel=Decimal(round(work / 7.2, 2)),
        stops=stops,
    )


def metrics(assigned: int, unassigned: int, engineers: int) -> ReportMetrics:
    return ReportMetrics(
        requests_count=assigned + unassigned,
        assigned_count=assigned,
        unassigned_count=unassigned,
        engineers_count=engineers,
        engineers_used_count=min(engineers, assigned),
        mileage_km=Decimal("21.75"),
        work_minutes=135,
        travel_minutes=60,
        utilization_with_travel=Decimal("27.08"),
        utilization_without_travel=Decimal("18.75"),
    )


def region_snapshot(region: Region = Region.VOSTOK) -> RegionReportSnapshot:
    initial, replan = uuid.uuid4(), uuid.uuid4()
    approved = datetime(2026, 9, 29, 7)
    busy = engineer(
        "Иванов Алексей",
        (stop(1, SHIFT_START + timedelta(minutes=20)), stop(2, SHIFT_START + timedelta(hours=2))),
    )
    return RegionReportSnapshot(
        region=region,
        planning_date=DAY,
        initial_plan_id=initial,
        upload_id=uuid.uuid4(),
        initial_approved_at=approved,
        baseline=ReportBaseline(2, 2, 2, Decimal("55.10"), Decimal("30.00"), Decimal("12.50")),
        initial_metrics=metrics(3, 1, 3),
        plans=(
            ReportPlanVersion(initial, PlanKind.INITIAL, approved, 3, 1, 2, Decimal("24.00"), None),
            ReportPlanVersion(
                replan,
                PlanKind.EVENT_REPLAN,
                approved + timedelta(hours=3),
                2,
                2,
                2,
                Decimal("21.75"),
                initial,
            ),
        ),
        changes=(ReportPlanChange(initial, replan, -1, 1, 0, Decimal("-2.25")),),
        events=(
            ReportEvent(
                uuid.uuid4(),
                ReplanningEventType.ENGINEER_UNAVAILABLE,
                approved + timedelta(hours=2, minutes=50),
                approved + timedelta(hours=3),
                "Петров Дмитрий",
            ),
        ),
        current_plan_id=replan,
        current_approved_at=approved + timedelta(hours=3),
        engineers=(
            busy,
            engineer("Сидоров Павел", (stop(3, SHIFT_START + timedelta(hours=5)),)),
            engineer("Петров Дмитрий", (), available=False),
        ),
        unassigned=(
            ReportUnassigned(2001, "Москва, Каширское ш., д. 5", UnassignedReason.NO_TIME_SLOT),
            ReportUnassigned(2002, "Москва, Перерва, д. 1", UnassignedReason.NO_ROUTE),
        ),
        metrics=metrics(3, 2, 3),
    )


def snapshot(*regions: RegionReportSnapshot) -> DailyReportSnapshot:
    return DailyReportSnapshot(
        planning_date=DAY,
        generated_at=datetime(2026, 9, 29, 18, 10),
        day_in_progress=True,
        regions=regions,
        summary=metrics(6, 4, 6),
    )


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type /Page\b", pdf))


class DailyPdfRenderTest(unittest.TestCase):
    def test_region_and_summary_files_are_valid_multi_page_pdfs(self) -> None:
        files = DailyPdfRenderer.render(
            snapshot(region_snapshot(), region_snapshot(Region.YUGO_VOSTOK))
        )

        self.assertEqual(set(files), {"vostok.pdf", "yugo_vostok.pdf", "summary.pdf"})
        for content in files.values():
            self.assertTrue(content.startswith(b"%PDF-"))
            self.assertIn(b"Onest", content)
        # Обзор, таймлайн + хронология + причины, маршруты инженеров.
        self.assertGreaterEqual(page_count(files["vostok.pdf"]), 3)
        self.assertGreaterEqual(page_count(files["summary.pdf"]), 1)

    def test_empty_day_renders_only_summary_note(self) -> None:
        files = DailyPdfRenderer.render(snapshot())

        self.assertEqual(set(files), {"summary.pdf"})
        self.assertEqual(page_count(files["summary.pdf"]), 1)

    def test_degenerate_region_data_does_not_break_charts(self) -> None:
        base = region_snapshot()
        idle = replace(
            base,
            engineers=tuple(replace(item, is_available=False, stops=()) for item in base.engineers),
            unassigned=(),
            events=(),
            changes=(),
            metrics=replace(base.metrics, work_minutes=0, travel_minutes=0, engineers_used_count=0),
        )
        late = replace(
            base,
            engineers=(
                replace(
                    base.engineers[0],
                    shift_end=SHIFT_START + timedelta(hours=15),
                    stops=(
                        replace(
                            stop(1, datetime(2026, 9, 30, 0, 30)),
                            address="Очень длинный адрес с кириллицей и подробностями " * 8,
                        ),
                    ),
                ),
            ),
        )

        for region in (idle, late):
            with self.subTest(engineers=len(region.engineers)):
                pdf = DailyPdfRenderer.render(snapshot(region))["vostok.pdf"]
                self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_long_route_splits_across_pages(self) -> None:
        base = region_snapshot()
        route = tuple(
            stop(number, SHIFT_START + timedelta(minutes=5 * number), work=5, travel=1)
            for number in range(1, 81)
        )
        region = replace(base, engineers=(engineer("Иванов Алексей", route),))

        pdf = DailyPdfRenderer.render(snapshot(region))["vostok.pdf"]

        self.assertGreater(
            page_count(pdf), page_count(DailyPdfRenderer.render(snapshot(base))["vostok.pdf"])
        )


class PdfFormattingTest(unittest.TestCase):
    def test_numbers_use_russian_separators_and_minus_sign(self) -> None:
        self.assertEqual(fmt_number(1814.83, 1), "1 814,8")
        self.assertEqual(fmt_signed(-2.25, 1), "−2,2")
        self.assertEqual(fmt_signed(3), "+3")
        self.assertEqual(fmt_signed(0.01, 1), "0,0")

    def test_durations_and_plural_forms(self) -> None:
        self.assertEqual(fmt_duration(45), "45 мин")
        self.assertEqual(fmt_duration(120), "2 ч")
        self.assertEqual(fmt_duration(125), "2 ч 05 мин")
        words = [DailyPdfRenderer._requests_word(count) for count in (1, 3, 5, 11, 22)]
        self.assertEqual(words, ["1 заявка", "3 заявки", "5 заявок", "11 заявок", "22 заявки"])

    def test_timeline_axis_covers_shifts_and_late_stops(self) -> None:
        late = replace(
            engineer("Иванов Алексей", (stop(1, datetime(2026, 9, 29, 22, 30)),)),
            shift_start=datetime(2026, 9, 29, 9, 15),
        )

        self.assertEqual(DailyPdfRenderer._timeline_hours((late,)), (9, 24))
