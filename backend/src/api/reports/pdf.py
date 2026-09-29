import math
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from html import escape
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from reportlab.lib.colors import Color
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    CondPageBreak,
    Flowable,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.api.reports.dto import (
    DailyReportSnapshot,
    RegionReportSnapshot,
    ReportEngineer,
    ReportEvent,
    ReportMetrics,
    ReportPlanChange,
    ReportPlanVersion,
)
from src.api.reports.pdf_components import (
    BAD,
    BAD_MILD,
    FONT,
    FONT_SEMIBOLD,
    GOOD,
    IDLE,
    INK,
    INK_SOFT,
    LINE,
    MUTED,
    TEAL,
    YELLOW,
    Bar,
    Better,
    CompareRow,
    ComparisonBars,
    Donut,
    EngineerHeader,
    Hero,
    HorizontalBars,
    Kpi,
    KpiCards,
    Note,
    RegionCard,
    RegionCards,
    SectionTitle,
    Segment,
    ShiftTimeline,
    StackedBars,
    StackedRow,
    TimelineEntry,
    TimelineItem,
    TimelineRow,
    TimelineStop,
    delta_tone,
    fmt_duration,
    fmt_number,
    fmt_signed,
    register_fonts,
)
from src.core.db.enums import PlanKind, Region, ReplanningEventType, UnassignedReason

PAGE = landscape(A4)
MARGIN_X = 34.0
MOSCOW = ZoneInfo("Europe/Moscow")
TIMELINE_ROWS_PER_BLOCK = 20
MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
DISCLAIMER = "Плановый отчёт. Фактическое исполнение заявок не подтверждается."


class _NumberedCanvas(Canvas):
    """Canvas с нумерацией «Страница N из M»: общее число страниц известно только в конце."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont(FONT, 7.5)
            self.setFillColor(MUTED)
            self.drawRightString(PAGE[0] - MARGIN_X, 20, f"Страница {self._pageNumber} из {total}")
            super().showPage()
        super().save()


class DailyPdfRenderer:
    """Создаёт PDF только из готового report snapshot, без доступа к БД."""

    @staticmethod
    def render(snapshot: DailyReportSnapshot) -> dict[str, bytes]:
        register_fonts()
        files = {
            f"{region.region.value}.pdf": DailyPdfRenderer._region_pdf(snapshot, region)
            for region in snapshot.regions
        }
        files["summary.pdf"] = DailyPdfRenderer._summary_pdf(snapshot)
        return files

    # === Документ ===

    @staticmethod
    def _document(buffer: BytesIO) -> SimpleDocTemplate:
        return SimpleDocTemplate(
            buffer,
            pagesize=PAGE,
            leftMargin=MARGIN_X,
            rightMargin=MARGIN_X,
            topMargin=46,
            bottomMargin=40,
            title="Плановый дневной отчёт",
            author="Beeline Business Route Planner",
        )

    @staticmethod
    def _width() -> float:
        return float(PAGE[0] - 2 * MARGIN_X)

    @staticmethod
    def _build(story: list[Flowable], context: str) -> bytes:
        buffer = BytesIO()
        document = DailyPdfRenderer._document(buffer)

        def decorate(canvas: Canvas, doc: SimpleDocTemplate) -> None:
            canvas.saveState()
            top = PAGE[1] - 26
            canvas.setFillColor(YELLOW)
            canvas.roundRect(MARGIN_X, top - 1, 14, 9, 2, stroke=0, fill=1)
            canvas.setFillColor(INK)
            canvas.setFont(FONT_SEMIBOLD, 8)
            canvas.drawString(MARGIN_X + 20, top, "Beeline Business Route Planner")
            canvas.setFont(FONT, 8)
            canvas.setFillColor(MUTED)
            canvas.drawRightString(PAGE[0] - MARGIN_X, top, context)
            canvas.setStrokeColor(LINE)
            canvas.setLineWidth(0.6)
            canvas.line(MARGIN_X, 32, PAGE[0] - MARGIN_X, 32)
            canvas.setFont(FONT, 7.5)
            canvas.drawString(MARGIN_X, 20, DISCLAIMER)
            canvas.restoreState()

        document.build(
            story, onFirstPage=decorate, onLaterPages=decorate, canvasmaker=_NumberedCanvas
        )
        return buffer.getvalue()

    # === Отчёт по округу ===

    @staticmethod
    def _region_pdf(snapshot: DailyReportSnapshot, region: RegionReportSnapshot) -> bytes:
        width = DailyPdfRenderer._width()
        name = DailyPdfRenderer._region_name(region.region)
        meta = (
            f"Сформирован {snapshot.generated_at:%d.%m.%Y %H:%M} МСК  ·  "
            f"последний план утверждён {DailyPdfRenderer._time_utc(region.current_approved_at)} "
            f"МСК  ·  версий плана: {len(region.plans)}  ·  событий: {len(region.events)}"
        )
        story: list[Flowable] = [
            Hero(
                width,
                name,
                f"Плановый отчёт за {DailyPdfRenderer._long_date(region.planning_date)}",
                DailyPdfRenderer._day_status(snapshot),
                meta,
            ),
            Spacer(1, 14),
            DailyPdfRenderer._kpis(region.metrics, width),
            Spacer(1, 18),
            DailyPdfRenderer._overview_columns(region, width),
            PageBreak(),
        ]
        story += DailyPdfRenderer._timeline_section(region, width)
        story += DailyPdfRenderer._chronology_section(region, width)
        story += DailyPdfRenderer._unassigned_section(region, width)
        story += DailyPdfRenderer._routes_section(region, width)
        return DailyPdfRenderer._build(story, f"{name}  ·  {region.planning_date:%d.%m.%Y}")

    @staticmethod
    def _kpis(metrics: ReportMetrics, width: float) -> KpiCards:
        requests = metrics.requests_count
        coverage = metrics.assigned_count / requests * 100 if requests else 0
        used = metrics.engineers_used_count
        mileage = float(metrics.mileage_km)
        unassigned_note = (
            f"{fmt_number(metrics.unassigned_count / requests * 100, 1)}% от всех заявок"
            if metrics.unassigned_count and requests
            else "все заявки в плане"
        )
        return KpiCards(
            width,
            [
                Kpi(
                    "Назначено заявок",
                    str(metrics.assigned_count),
                    f"покрытие {fmt_number(coverage, 1)}%",
                    accent=True,
                    unit=f"из {requests}",
                ),
                Kpi("Не назначено", str(metrics.unassigned_count), unassigned_note),
                Kpi(
                    "Инженеров на маршрутах",
                    str(used),
                    f"≈ {fmt_number(metrics.assigned_count / used, 1)} заявки на инженера"
                    if used
                    else "маршрутов нет",
                    unit=f"из {metrics.engineers_count}",
                ),
                Kpi(
                    "Пробег",
                    fmt_number(mileage, 1),
                    f"≈ {fmt_number(mileage / used, 1)} км на инженера" if used else "",
                    unit="км",
                ),
                Kpi(
                    "Загрузка с дорогой",
                    fmt_number(float(metrics.utilization_with_travel), 1),
                    f"без дороги {fmt_number(float(metrics.utilization_without_travel), 1)}%",
                    unit="%",
                ),
            ],
        )

    @staticmethod
    def _overview_columns(region: RegionReportSnapshot, width: float) -> Table:
        gap = 30.0
        left_width = width * 0.56
        right_width = width - left_width - gap
        initial, baseline = region.initial_metrics, region.baseline
        comparison = ComparisonBars(
            left_width,
            [
                CompareRow(
                    "Назначено заявок",
                    initial.assigned_count,
                    baseline.assigned_count,
                    better="higher",
                ),
                CompareRow(
                    "Не назначено",
                    initial.unassigned_count,
                    baseline.unassigned_count,
                    better="lower",
                ),
                CompareRow(
                    "Пробег, км",
                    float(initial.mileage_km),
                    float(baseline.mileage_km),
                    digits=1,
                    better="lower",
                ),
                CompareRow(
                    "Загрузка без дороги, %",
                    float(initial.utilization_without_travel),
                    float(baseline.utilization_without_travel),
                    digits=1,
                    better="higher",
                ),
                CompareRow(
                    "Загрузка с дорогой, %",
                    float(initial.utilization_with_travel),
                    float(baseline.utilization_with_travel),
                    digits=1,
                ),
                CompareRow(
                    "Инженеров с маршрутом",
                    initial.engineers_used_count,
                    baseline.engineers_used_count,
                ),
            ],
            legend=("Исходный план", "Baseline"),
        )
        left = [
            SectionTitle(
                left_width,
                "Оптимизация против baseline",
                "Утверждённый исходный план в сравнении с эталонным распределением",
            ),
            Spacer(1, 6),
            comparison,
        ]
        right = [
            SectionTitle(
                right_width,
                "Структура рабочего времени",
                "Фонд смен доступных инженеров итогового плана",
            ),
            Spacer(1, 16),
            DailyPdfRenderer._time_donut(region, right_width),
        ]
        return DailyPdfRenderer._columns([left, right], [left_width + gap, right_width])

    @staticmethod
    def _time_segments(region: RegionReportSnapshot) -> tuple[int, tuple[Segment, ...]]:
        capacity = sum(
            DailyPdfRenderer._minutes(engineer.shift_end - engineer.shift_start)
            for engineer in region.engineers
            if engineer.is_available
        )
        work = region.metrics.work_minutes
        travel = region.metrics.travel_minutes
        idle = max(capacity - work - travel, 0)
        return capacity, (
            Segment("Работа на заявках", work, YELLOW, fmt_duration(work)),
            Segment("Дорога", travel, TEAL, fmt_duration(travel)),
            Segment("Свободно", idle, IDLE, fmt_duration(idle)),
        )

    @staticmethod
    def _time_donut(region: RegionReportSnapshot, width: float) -> Donut:
        capacity, segments = DailyPdfRenderer._time_segments(region)
        return Donut(width, segments, f"{fmt_number(capacity / 60)} ч", "фонд смен")

    @staticmethod
    def _time_row(label: str, region: RegionReportSnapshot) -> StackedRow:
        capacity, segments = DailyPdfRenderer._time_segments(region)
        return StackedRow(label, segments, f"фонд {fmt_number(capacity / 60)} ч")

    @staticmethod
    def _timeline_section(region: RegionReportSnapshot, width: float) -> list[Flowable]:
        story: list[Flowable] = [
            SectionTitle(
                width,
                "Таймлайн смены",
                "Когда каждый инженер в дороге и на заявках. Справа — загрузка смены с дорогой.",
            ),
            Spacer(1, 8),
        ]
        rows = sorted(
            (DailyPdfRenderer._timeline_row(engineer) for engineer in region.engineers),
            key=lambda row: (not row.available, -row.utilization),
        )
        if not rows:
            return [*story, Note(width, "В плане нет инженеров."), Spacer(1, 18)]
        hours = DailyPdfRenderer._timeline_hours(region.engineers)
        for start in range(0, len(rows), TIMELINE_ROWS_PER_BLOCK):
            chunk = rows[start : start + TIMELINE_ROWS_PER_BLOCK]
            story += [ShiftTimeline(width, chunk, hours), Spacer(1, 10)]
        return [*story, Spacer(1, 8)]

    @staticmethod
    def _timeline_row(engineer: ReportEngineer) -> TimelineRow:
        return TimelineRow(
            engineer.name,
            engineer.shift_start,
            engineer.shift_end,
            engineer.is_available,
            float(engineer.utilization_with_travel),
            tuple(
                TimelineStop(
                    stop.sequence_number,
                    stop.planned_arrival,
                    stop.planned_start,
                    stop.planned_finish,
                    stop.travel_minutes,
                )
                for stop in engineer.stops
            ),
        )

    @staticmethod
    def _timeline_hours(engineers: Sequence[ReportEngineer]) -> tuple[int, int]:
        day = datetime.combine(min(e.shift_start for e in engineers).date(), datetime.min.time())
        moments = [e.shift_start for e in engineers] + [e.shift_end for e in engineers]
        moments += [stop.planned_finish for e in engineers for stop in e.stops]
        first = math.floor(min((m - day).total_seconds() for m in moments) / 3600)
        last = math.ceil(max((m - day).total_seconds() for m in moments) / 3600)
        return max(first, 0), max(last, first + 1)

    @staticmethod
    def _chronology_section(region: RegionReportSnapshot, width: float) -> list[Flowable]:
        changes = {change.plan_id: change for change in region.changes}
        # При равном времени событие идёт раньше пересчёта, который оно вызвало.
        entries: list[tuple[datetime, int, TimelineEntry]] = [
            (plan.approved_at, 1, DailyPdfRenderer._plan_entry(plan, changes.get(plan.id)))
            for plan in region.plans
        ]
        entries += [
            (event.occurred_at, 0, DailyPdfRenderer._event_entry(event)) for event in region.events
        ]
        entries.sort(key=lambda item: item[:2])
        story: list[Flowable] = [
            CondPageBreak(160),
            SectionTitle(
                width,
                "Хронология дня",
                "Утверждённые версии плана и внештатные события, время московское",
            ),
            Spacer(1, 6),
        ]
        story += [
            TimelineItem(width, entry, first=index == 0, last=index == len(entries) - 1)
            for index, (_, _, entry) in enumerate(entries)
        ]
        return [*story, Spacer(1, 18)]

    @staticmethod
    def _plan_entry(plan: ReportPlanVersion, change: ReportPlanChange | None) -> TimelineEntry:
        title = {
            PlanKind.INITIAL: "Утверждён исходный план",
            PlanKind.REPLAN: "Утверждено перепланирование",
            PlanKind.EVENT_REPLAN: "Утверждён пересчёт по событию",
        }[plan.kind]
        chips: list[tuple[str, Color, Color]] = []
        if change is not None:
            deltas: tuple[tuple[str, float, int, str, Better], ...] = (
                ("назначено", change.assigned_delta, 0, "", "higher"),
                ("не назначено", change.unassigned_delta, 0, "", "lower"),
                ("инженеров", change.engineers_used_delta, 0, "", None),
                ("пробег", float(change.mileage_delta_km), 1, " км", "lower"),
            )
            for label, delta, digits, unit, better in deltas:
                if round(delta, digits) != 0:
                    fg, bg = delta_tone(delta, better)
                    chips.append((f"{label} {fmt_signed(delta, digits)}{unit}", fg, bg))
        return TimelineEntry(
            DailyPdfRenderer._clock_utc(plan.approved_at),
            title,
            f"Назначено {plan.assigned_count}, не назначено {plan.unassigned_count}, "
            f"инженеров {plan.engineers_used_count}, пробег "
            f"{fmt_number(float(plan.mileage_km), 1)} км  ·  версия {str(plan.id)[-8:]}",
            YELLOW,
            tuple(chips),
        )

    @staticmethod
    def _event_entry(event: ReportEvent) -> TimelineEntry:
        color = {
            ReplanningEventType.URGENT_REQUEST: BAD,
            ReplanningEventType.REQUEST_CANCELLED: MUTED,
            ReplanningEventType.ENGINEER_UNAVAILABLE: BAD,
            ReplanningEventType.ENGINEER_AVAILABLE: GOOD,
        }[event.event_type]
        return TimelineEntry(
            DailyPdfRenderer._clock_utc(event.occurred_at),
            DailyPdfRenderer._event_name(event.event_type),
            f"{event.target}  ·  утверждено в {DailyPdfRenderer._clock_utc(event.approved_at)}",
            color,
        )

    @staticmethod
    def _unassigned_section(region: RegionReportSnapshot, width: float) -> list[Flowable]:
        story: list[Flowable] = [
            CondPageBreak(140),
            SectionTitle(width, "Неназначенные заявки", "Почему заявки не попали в маршруты"),
            Spacer(1, 6),
        ]
        if not region.unassigned:
            return [*story, Note(width, "Все заявки назначены.", tone="good"), Spacer(1, 18)]
        reasons = Counter(item.reason for item in region.unassigned)
        story += [
            HorizontalBars(
                width * 0.6,
                [
                    Bar(DailyPdfRenderer._reason(reason), count, BAD if index == 0 else BAD_MILD)
                    for index, (reason, count) in enumerate(reasons.most_common())
                ],
                lambda value: DailyPdfRenderer._requests_word(int(value)),
            ),
            Spacer(1, 12),
        ]
        rows: list[list[object]] = [["Заявка", "Адрес", "Причина"]]
        rows += [
            [item.external_id, item.address, DailyPdfRenderer._reason(item.reason)]
            for item in region.unassigned
        ]
        story.append(DailyPdfRenderer._table(rows, (12, 60, 28), width))
        return [*story, Spacer(1, 18)]

    @staticmethod
    def _routes_section(region: RegionReportSnapshot, width: float) -> list[Flowable]:
        story: list[Flowable] = [
            PageBreak(),
            SectionTitle(
                width,
                "Маршруты инженеров",
                "Порядок заявок в итоговом утверждённом плане, время московское",
            ),
            Spacer(1, 6),
        ]
        for engineer in region.engineers:
            story += DailyPdfRenderer._engineer_block(engineer, width)
        return story

    @staticmethod
    def _engineer_block(engineer: ReportEngineer, width: float) -> list[Flowable]:
        chips = [
            f"Смена {engineer.shift_start:%H:%M}–{engineer.shift_end:%H:%M}",
            DailyPdfRenderer._requests_word(len(engineer.stops)),
            f"работа {fmt_duration(engineer.work_minutes)}",
            f"дорога {fmt_duration(engineer.travel_minutes)}",
            f"{fmt_number(float(engineer.mileage_km), 1)} км",
            f"без дороги {fmt_number(float(engineer.utilization_without_travel), 1)}%",
        ]
        story: list[Flowable] = [
            CondPageBreak(110),
            EngineerHeader(
                width,
                engineer.name,
                chips,
                float(engineer.utilization_with_travel),
                engineer.is_available,
            ),
            Spacer(1, 4),
        ]
        if not engineer.stops:
            return [*story, Note(width, "Назначенных заявок нет."), Spacer(1, 14)]
        rows: list[list[object]] = [
            [
                "№",
                "Заявка",
                "Адрес",
                "Прибытие",
                "На заявке",
                "Работа",
                "Дорога",
                "Км",
                "Закреплена",
            ]
        ]
        rows += [
            [
                stop.sequence_number,
                stop.external_id,
                stop.address,
                f"{stop.planned_arrival:%H:%M}",
                f"{stop.planned_start:%H:%M}–{stop.planned_finish:%H:%M}",
                f"{stop.work_minutes} мин",
                f"{stop.travel_minutes} мин",
                fmt_number(float(stop.distance_km), 1),
                "да" if stop.is_locked else "—",
            ]
            for stop in engineer.stops
        ]
        table = DailyPdfRenderer._table(
            rows, (4, 8, 40, 8, 11, 8, 8, 6, 8), width, right_columns={5, 6, 7}
        )
        return [*story, table, Spacer(1, 16)]

    # === Сводный отчёт ===

    @staticmethod
    def _summary_pdf(snapshot: DailyReportSnapshot) -> bytes:
        width = DailyPdfRenderer._width()
        regions = snapshot.regions
        story: list[Flowable] = [
            Hero(
                width,
                "Сводный отчёт",
                f"Все округа за {DailyPdfRenderer._long_date(snapshot.planning_date)}",
                DailyPdfRenderer._day_status(snapshot),
                f"Сформирован {snapshot.generated_at:%d.%m.%Y %H:%M} МСК  ·  "
                f"округов с утверждённым планом: {len(regions)}",
            ),
            Spacer(1, 14),
        ]
        if not regions:
            story.append(Note(width, "Нет округов с утверждённым планом на эту дату."))
            return DailyPdfRenderer._build(story, f"Сводка  ·  {snapshot.planning_date:%d.%m.%Y}")
        story += [
            DailyPdfRenderer._kpis(snapshot.summary, width),
            Spacer(1, 18),
            SectionTitle(width, "Округа", "Покрытие заявок и ключевые цифры итоговых планов"),
            Spacer(1, 6),
            RegionCards(width, [DailyPdfRenderer._region_card(region) for region in regions]),
            Spacer(1, 18),
            CondPageBreak(200),
            DailyPdfRenderer._summary_comparison(regions, width),
            Spacer(1, 18),
            CondPageBreak(160),
            SectionTitle(
                width,
                "Структура рабочего времени по округам",
                "Доли работы, дороги и свободного времени в фонде смен доступных инженеров",
            ),
            Spacer(1, 6),
            StackedBars(
                width,
                [
                    DailyPdfRenderer._time_row(DailyPdfRenderer._region_name(r.region), r)
                    for r in regions
                ],
            ),
            Spacer(1, 18),
            CondPageBreak(120),
            SectionTitle(width, "Итоги по округам"),
            Spacer(1, 4),
            DailyPdfRenderer._summary_table(regions, width),
        ]
        return DailyPdfRenderer._build(story, f"Сводка  ·  {snapshot.planning_date:%d.%m.%Y}")

    @staticmethod
    def _region_card(region: RegionReportSnapshot) -> RegionCard:
        metrics = region.metrics
        return RegionCard(
            DailyPdfRenderer._region_name(region.region),
            metrics.assigned_count,
            metrics.requests_count,
            (
                ("Не назначено", str(metrics.unassigned_count)),
                (
                    "Инженеров на маршрутах",
                    f"{metrics.engineers_used_count} из {metrics.engineers_count}",
                ),
                ("Пробег", f"{fmt_number(float(metrics.mileage_km), 1)} км"),
                (
                    "Загрузка с дорогой",
                    f"{fmt_number(float(metrics.utilization_with_travel), 1)}%",
                ),
                ("Версий плана / событий", f"{len(region.plans)} / {len(region.events)}"),
            ),
        )

    @staticmethod
    def _summary_comparison(regions: Sequence[RegionReportSnapshot], width: float) -> Table:
        gap = 30.0
        column = (width - gap) / 2
        names = [DailyPdfRenderer._region_name(region.region) for region in regions]
        assigned = ComparisonBars(
            column,
            [
                CompareRow(
                    name,
                    r.initial_metrics.assigned_count,
                    r.baseline.assigned_count,
                    better="higher",
                )
                for name, r in zip(names, regions, strict=True)
            ],
            legend=("Исходный план", "Baseline"),
        )
        mileage = ComparisonBars(
            column,
            [
                CompareRow(
                    name,
                    float(r.initial_metrics.mileage_km),
                    float(r.baseline.mileage_km),
                    digits=1,
                    unit=" км",
                    better="lower",
                )
                for name, r in zip(names, regions, strict=True)
            ],
            legend=("Исходный план", "Baseline"),
        )
        left = [
            SectionTitle(column, "Назначено заявок", "Исходный план против baseline"),
            Spacer(1, 6),
            assigned,
        ]
        right = [
            SectionTitle(column, "Пробег", "Исходный план против baseline"),
            Spacer(1, 6),
            mileage,
        ]
        return DailyPdfRenderer._columns([left, right], [column + gap, column])

    @staticmethod
    def _summary_table(regions: Sequence[RegionReportSnapshot], width: float) -> LongTable:
        rows: list[list[object]] = [
            [
                "Округ",
                "Заявок",
                "Назначено",
                "Не назначено",
                "Инженеров",
                "Пробег, км",
                "Загрузка, %",
                "Перепланирований",
                "Событий",
            ]
        ]
        rows += [
            [
                DailyPdfRenderer._region_name(region.region),
                region.metrics.requests_count,
                region.metrics.assigned_count,
                region.metrics.unassigned_count,
                f"{region.metrics.engineers_used_count} из {region.metrics.engineers_count}",
                fmt_number(float(region.metrics.mileage_km), 1),
                fmt_number(float(region.metrics.utilization_with_travel), 1),
                len(region.plans) - 1,
                len(region.events),
            ]
            for region in regions
        ]
        return DailyPdfRenderer._table(
            rows,
            (16, 9, 10, 11, 11, 11, 11, 13, 8),
            width,
            right_columns={1, 2, 3, 4, 5, 6, 7, 8},
        )

    # === Общие блоки ===

    @staticmethod
    def _columns(columns: list[list[Flowable]], widths: list[float]) -> Table:
        table = Table([columns], colWidths=widths, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return table

    @staticmethod
    def _cell_styles() -> dict[str, ParagraphStyle]:
        base = ParagraphStyle(
            "ReportCell",
            fontName=FONT,
            fontSize=8,
            leading=10.5,
            textColor=INK,
            splitLongWords=1,
        )
        header = ParagraphStyle(
            "ReportHeader", parent=base, fontName=FONT_SEMIBOLD, fontSize=7.5, textColor=MUTED
        )
        return {
            "cell": base,
            "cell_right": ParagraphStyle("ReportCellRight", parent=base, alignment=TA_RIGHT),
            "header": header,
            "header_right": ParagraphStyle("ReportHeaderRight", parent=header, alignment=TA_RIGHT),
        }

    @staticmethod
    def _table(
        rows: list[list[object]],
        weights: tuple[int, ...],
        width: float,
        right_columns: set[int] | None = None,
    ) -> LongTable:
        right = right_columns or set()
        styles = DailyPdfRenderer._cell_styles()
        total = sum(weights)
        data = [
            [
                Paragraph(
                    escape(str(value)),
                    styles[
                        ("header" if index == 0 else "cell") + ("_right" if column in right else "")
                    ],
                )
                for column, value in enumerate(row)
            ]
            for index, row in enumerate(rows)
        ]
        table = LongTable(
            data, colWidths=[width * w / total for w in weights], repeatRows=1, hAlign="LEFT"
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, 0), 1.4, YELLOW),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
                    ("TEXTCOLOR", (0, 1), (-1, -1), INK_SOFT),
                ]
            )
        )
        return table

    @staticmethod
    def _day_status(snapshot: DailyReportSnapshot) -> tuple[str, bool]:
        return ("День в работе", True) if snapshot.day_in_progress else ("День завершён", False)

    @staticmethod
    def _long_date(value: date) -> str:
        return f"{value.day} {MONTHS[value.month - 1]} {value.year}"

    @staticmethod
    def _minutes(value: timedelta) -> int:
        return int(value.total_seconds() // 60)

    @staticmethod
    def _requests_word(count: int) -> str:
        if count % 10 == 1 and count % 100 != 11:
            word = "заявка"
        elif 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
            word = "заявки"
        else:
            word = "заявок"
        return f"{count} {word}"

    @staticmethod
    def _time_utc(value: datetime) -> str:
        return value.replace(tzinfo=UTC).astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")

    @staticmethod
    def _clock_utc(value: datetime) -> str:
        return value.replace(tzinfo=UTC).astimezone(MOSCOW).strftime("%H:%M")

    @staticmethod
    def _region_name(region: Region) -> str:
        match region:
            case Region.VOSTOK:
                return "Восток"
            case Region.YUGO_VOSTOK:
                return "Юго-восток"
            case Region.YUGOTSENTR:
                return "Югоцентр"

    @staticmethod
    def _event_name(event_type: ReplanningEventType) -> str:
        match event_type:
            case ReplanningEventType.URGENT_REQUEST:
                return "Срочная заявка"
            case ReplanningEventType.REQUEST_CANCELLED:
                return "Отмена заявки"
            case ReplanningEventType.ENGINEER_UNAVAILABLE:
                return "Выбытие инженера"
            case ReplanningEventType.ENGINEER_AVAILABLE:
                return "Возвращение инженера"

    @staticmethod
    def _reason(reason: UnassignedReason) -> str:
        match reason:
            case UnassignedReason.NO_MATCHING_SKILL:
                return "Нет подходящего навыка"
            case UnassignedReason.NO_MATCHING_VEHICLE:
                return "Нет подходящего транспорта"
            case UnassignedReason.NO_TIME_SLOT:
                return "Нет свободного окна"
            case UnassignedReason.NO_ROUTE:
                return "Нет маршрута до адреса"
            case UnassignedReason.NO_AVAILABLE_ENGINEER:
                return "Нет доступного инженера"
