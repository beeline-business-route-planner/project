from datetime import UTC, datetime
from html import escape
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

from src.api.reports.dto import (
    DailyReportSnapshot,
    RegionReportSnapshot,
    ReportEngineer,
    ReportMetrics,
)
from src.core.db.enums import PlanKind, Region, ReplanningEventType, UnassignedReason


class DailyPdfRenderer:
    """Создаёт PDF только из готового report snapshot, без доступа к БД."""

    @staticmethod
    def render(snapshot: DailyReportSnapshot) -> dict[str, bytes]:
        DailyPdfRenderer._register_font()
        files = {
            f"{region.region.value}.pdf": DailyPdfRenderer._region_pdf(snapshot, region)
            for region in snapshot.regions
        }
        files["summary.pdf"] = DailyPdfRenderer._summary_pdf(snapshot)
        return files

    @staticmethod
    def _register_font() -> None:
        name = "T08DejaVuSans"
        if name not in pdfmetrics.getRegisteredFontNames():
            font_path = Path(__file__).parent / "assets" / "DejaVuSans.ttf"
            pdfmetrics.registerFont(TTFont(name, str(font_path)))
            pdfmetrics.registerFontFamily(name, normal=name, bold=name, italic=name)

    @staticmethod
    def _styles() -> dict[str, ParagraphStyle]:
        font = "T08DejaVuSans"
        return {
            "title": ParagraphStyle(
                "T08Title",
                fontName=font,
                fontSize=17,
                leading=22,
                textColor=colors.HexColor("#17243A"),
            ),
            "section": ParagraphStyle(
                "T08Section",
                fontName=font,
                fontSize=11,
                leading=15,
                textColor=colors.HexColor("#17243A"),
                spaceBefore=12,
                spaceAfter=6,
            ),
            "body": ParagraphStyle(
                "T08Body",
                fontName=font,
                fontSize=8,
                leading=11,
                textColor=colors.HexColor("#24344B"),
                splitLongWords=1,
            ),
            "small": ParagraphStyle(
                "T08Small",
                fontName=font,
                fontSize=7,
                leading=9,
                textColor=colors.HexColor("#24344B"),
                splitLongWords=1,
            ),
            "header": ParagraphStyle(
                "T08Header",
                fontName=font,
                fontSize=7,
                leading=9,
                textColor=colors.white,
                splitLongWords=1,
            ),
            "center": ParagraphStyle(
                "T08Center",
                fontName=font,
                fontSize=8,
                leading=11,
                textColor=colors.HexColor("#24344B"),
                alignment=TA_CENTER,
            ),
        }

    @staticmethod
    def _document(buffer: BytesIO) -> SimpleDocTemplate:
        return SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            leftMargin=34,
            rightMargin=34,
            topMargin=37,
            bottomMargin=38,
            title="Плановый дневной отчёт",
            author="Beeline Business Route Planner",
        )

    @staticmethod
    def _build(story: list) -> bytes:
        buffer = BytesIO()
        document = DailyPdfRenderer._document(buffer)

        def footer(canvas, doc) -> None:
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor("#DCE3EC"))
            canvas.line(34, 31, landscape(A4)[0] - 34, 31)
            canvas.setFont("T08DejaVuSans", 7)
            canvas.setFillColor(colors.HexColor("#617185"))
            canvas.drawString(34, 20, "Плановый отчёт. Фактическое исполнение не подтверждается.")
            canvas.drawRightString(landscape(A4)[0] - 34, 20, f"Страница {doc.page}")
            canvas.restoreState()

        document.build(story, onFirstPage=footer, onLaterPages=footer)
        return buffer.getvalue()

    @staticmethod
    def _paragraph(text: object, style: ParagraphStyle) -> Paragraph:
        return Paragraph(escape(str(text)), style)

    @staticmethod
    def _table(
        rows: list[list[object]],
        weights: tuple[int, ...],
        width: float,
        styles: dict[str, ParagraphStyle],
    ) -> LongTable:
        total = sum(weights)
        columns = [width * weight / total for weight in weights]
        data = [
            [
                DailyPdfRenderer._paragraph(
                    value, styles["header"] if index == 0 else styles["small"]
                )
                for value in row
            ]
            for index, row in enumerate(rows)
        ]
        table = LongTable(data, colWidths=columns, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263B59")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#F2F5F9")],
                    ),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#DCE3EC")),
                ]
            )
        )
        return table

    @staticmethod
    def _section(story: list, title: str, styles: dict[str, ParagraphStyle]) -> None:
        story.append(CondPageBreak(90))
        story.append(DailyPdfRenderer._paragraph(title, styles["section"]))

    @staticmethod
    def _region_pdf(snapshot: DailyReportSnapshot, region: RegionReportSnapshot) -> bytes:
        styles = DailyPdfRenderer._styles()
        width = DailyPdfRenderer._document(BytesIO()).width
        story: list = [
            DailyPdfRenderer._paragraph(
                f"Плановый отчёт: {DailyPdfRenderer._region_name(region.region)}", styles["title"]
            ),
            Spacer(1, 5),
            DailyPdfRenderer._paragraph(
                f"Рабочая дата: {region.planning_date:%d.%m.%Y}  |  "
                f"Сформирован: {snapshot.generated_at:%d.%m.%Y %H:%M} МСК  |  "
                f"День продолжается: {'да' if snapshot.day_in_progress else 'нет'}",
                styles["body"],
            ),
            Spacer(1, 4),
            DailyPdfRenderer._paragraph(
                f"Утверждённый initial: {region.initial_plan_id} "
                f"({DailyPdfRenderer._time_utc(region.initial_approved_at)} МСК), "
                f"загрузка {region.upload_id}. Последний утверждённый план: "
                f"{region.current_plan_id} "
                f"({DailyPdfRenderer._time_utc(region.current_approved_at)} МСК).",
                styles["body"],
            ),
        ]
        DailyPdfRenderer._section(story, "Итоговые показатели", styles)
        story.append(DailyPdfRenderer._metrics_table(region.metrics, width, styles))
        DailyPdfRenderer._section(story, "Initial и baseline", styles)
        story.append(DailyPdfRenderer._baseline_table(region, width, styles))
        DailyPdfRenderer._section(story, "Хронология утверждённых планов", styles)
        plan_rows: list[list[object]] = [
            [
                "Утверждён (МСК)",
                "Тип",
                "План",
                "Назначено",
                "Не назначено",
                "Инженеров",
                "Пробег, км",
            ]
        ]
        plan_rows.extend(
            [
                DailyPdfRenderer._time_utc(plan.approved_at),
                DailyPdfRenderer._kind_name(plan.kind),
                str(plan.id)[-12:],
                plan.assigned_count,
                plan.unassigned_count,
                plan.engineers_used_count,
                f"{plan.mileage_km:.2f}",
            ]
            for plan in region.plans
        )
        story.append(
            DailyPdfRenderer._table(plan_rows, (19, 16, 12, 12, 15, 13, 13), width, styles)
        )
        if region.changes:
            DailyPdfRenderer._section(story, "Изменения между версиями", styles)
            rows: list[list[object]] = [
                ["Версии", "Назначено Δ", "Не назначено Δ", "Инженеры Δ", "Пробег Δ, км"]
            ]
            rows.extend(
                [
                    f"{str(item.previous_plan_id)[-12:]} → {str(item.plan_id)[-12:]}",
                    f"{item.assigned_delta:+d}",
                    f"{item.unassigned_delta:+d}",
                    f"{item.engineers_used_delta:+d}",
                    f"{item.mileage_delta_km:+.2f}",
                ]
                for item in region.changes
            )
            story.append(DailyPdfRenderer._table(rows, (32, 17, 20, 15, 16), width, styles))
        DailyPdfRenderer._section(story, "Утверждённые внештатные события", styles)
        if region.events:
            rows = [["Событие", "Цель", "Возникло (МСК)", "Утверждено (МСК)"]]
            rows.extend(
                [
                    DailyPdfRenderer._event_name(item.event_type),
                    item.target,
                    DailyPdfRenderer._time_utc(item.occurred_at),
                    DailyPdfRenderer._time_utc(item.approved_at),
                ]
                for item in region.events
            )
            story.append(DailyPdfRenderer._table(rows, (25, 30, 22, 23), width, styles))
        else:
            story.append(DailyPdfRenderer._paragraph("Нет утверждённых событий.", styles["body"]))
        DailyPdfRenderer._section(story, "Итоговые маршруты инженеров", styles)
        for engineer in region.engineers:
            DailyPdfRenderer._engineer_section(story, engineer, width, styles)
        DailyPdfRenderer._section(story, "Неназначенные заявки", styles)
        if region.unassigned:
            rows = [["Заявка", "Адрес", "Причина"]]
            rows.extend(
                [item.external_id, item.address, DailyPdfRenderer._reason(item.reason)]
                for item in region.unassigned
            )
            story.append(DailyPdfRenderer._table(rows, (13, 57, 30), width, styles))
        else:
            story.append(DailyPdfRenderer._paragraph("Неназначенных заявок нет.", styles["body"]))
        return DailyPdfRenderer._build(story)

    @staticmethod
    def _engineer_section(
        story: list, engineer: ReportEngineer, width: float, styles: dict[str, ParagraphStyle]
    ) -> None:
        DailyPdfRenderer._section(story, engineer.name, styles)
        story.append(
            DailyPdfRenderer._paragraph(
                f"Смена {engineer.shift_start:%H:%M}-{engineer.shift_end:%H:%M}; "
                f"доступен: {'да' if engineer.is_available else 'нет'}; "
                f"работа {engineer.work_minutes} мин; дорога {engineer.travel_minutes} мин; "
                f"пробег {engineer.mileage_km:.2f} км; загрузка с дорогой "
                f"{engineer.utilization_with_travel:.2f}%, без дороги "
                f"{engineer.utilization_without_travel:.2f}%.",
                styles["body"],
            )
        )
        if not engineer.stops:
            story.append(DailyPdfRenderer._paragraph("Назначенных остановок нет.", styles["body"]))
            return
        rows: list[list[object]] = [
            [
                "№",
                "Заявка",
                "Адрес",
                "Прибытие",
                "Начало",
                "Конец",
                "Работа, мин",
                "Дорога, мин",
                "Км",
                "Ист.",
            ]
        ]
        rows.extend(
            [
                item.sequence_number,
                item.external_id,
                item.address,
                item.planned_arrival.strftime("%H:%M"),
                item.planned_start.strftime("%H:%M"),
                item.planned_finish.strftime("%H:%M"),
                item.work_minutes,
                item.travel_minutes,
                f"{item.distance_km:.2f}",
                "да" if item.is_locked else "нет",
            ]
            for item in engineer.stops
        )
        story.append(DailyPdfRenderer._table(rows, (5, 9, 31, 9, 9, 9, 9, 10, 5, 4), width, styles))

    @staticmethod
    def _summary_pdf(snapshot: DailyReportSnapshot) -> bytes:
        styles = DailyPdfRenderer._styles()
        width = DailyPdfRenderer._document(BytesIO()).width
        story: list = [
            DailyPdfRenderer._paragraph("Сводный плановый отчёт", styles["title"]),
            Spacer(1, 5),
            DailyPdfRenderer._paragraph(
                f"Рабочая дата: {snapshot.planning_date:%d.%m.%Y}  |  "
                f"Сформирован: {snapshot.generated_at:%d.%m.%Y %H:%M} МСК  |  "
                f"День продолжается: {'да' if snapshot.day_in_progress else 'нет'}",
                styles["body"],
            ),
        ]
        DailyPdfRenderer._section(story, "Участвовавшие округа", styles)
        if snapshot.regions:
            rows: list[list[object]] = [
                [
                    "Округ",
                    "Заявок",
                    "Назначено",
                    "Не назначено",
                    "Инженеров",
                    "Пробег, км",
                    "Replans",
                    "События",
                ]
            ]
            rows.extend(
                [
                    DailyPdfRenderer._region_name(region.region),
                    region.metrics.requests_count,
                    region.metrics.assigned_count,
                    region.metrics.unassigned_count,
                    region.metrics.engineers_count,
                    f"{region.metrics.mileage_km:.2f}",
                    len(region.plans) - 1,
                    len(region.events),
                ]
                for region in snapshot.regions
            )
            story.append(
                DailyPdfRenderer._table(rows, (19, 10, 12, 16, 13, 13, 9, 8), width, styles)
            )
        else:
            story.append(
                DailyPdfRenderer._paragraph("Нет округов с утверждённым планом.", styles["body"])
            )
        DailyPdfRenderer._section(story, "Сводные показатели", styles)
        story.append(DailyPdfRenderer._metrics_table(snapshot.summary, width, styles))
        DailyPdfRenderer._section(story, "Initial против baseline по округам", styles)
        if snapshot.regions:
            rows = [
                [
                    "Округ",
                    "Назначено initial / baseline",
                    "Пробег initial / baseline, км",
                    "Загрузка с дорогой initial / baseline, %",
                    "Загрузка без дороги initial / baseline, %",
                ]
            ]
            rows.extend(
                [
                    DailyPdfRenderer._region_name(region.region),
                    f"{region.initial_metrics.assigned_count} / {region.baseline.assigned_count}",
                    f"{region.initial_metrics.mileage_km:.2f} / {region.baseline.mileage_km:.2f}",
                    f"{region.initial_metrics.utilization_with_travel:.2f} / "
                    f"{region.baseline.utilization_with_travel:.2f}",
                    f"{region.initial_metrics.utilization_without_travel:.2f} / "
                    f"{region.baseline.utilization_without_travel:.2f}",
                ]
                for region in snapshot.regions
            )
            story.append(DailyPdfRenderer._table(rows, (16, 19, 19, 23, 23), width, styles))
        return DailyPdfRenderer._build(story)

    @staticmethod
    def _metrics_table(
        metrics: ReportMetrics, width: float, styles: dict[str, ParagraphStyle]
    ) -> LongTable:
        rows: list[list[object]] = [["Показатель", "Значение", "Показатель", "Значение"]]
        rows.extend(
            [
                [
                    "Заявок всего",
                    metrics.requests_count,
                    "Назначено / не назначено",
                    f"{metrics.assigned_count} / {metrics.unassigned_count}",
                ],
                [
                    "Инженеров всего",
                    metrics.engineers_count,
                    "Инженеров с маршрутом",
                    metrics.engineers_used_count,
                ],
                [
                    "Пробег, км",
                    f"{metrics.mileage_km:.2f}",
                    "Работа / дорога, мин",
                    f"{metrics.work_minutes} / {metrics.travel_minutes}",
                ],
                [
                    "Загрузка с дорогой, %",
                    f"{metrics.utilization_with_travel:.2f}",
                    "Загрузка без дороги, %",
                    f"{metrics.utilization_without_travel:.2f}",
                ],
            ]
        )
        return DailyPdfRenderer._table(rows, (29, 17, 36, 18), width, styles)

    @staticmethod
    def _baseline_table(
        region: RegionReportSnapshot, width: float, styles: dict[str, ParagraphStyle]
    ) -> LongTable:
        initial = region.initial_metrics
        baseline = region.baseline
        without_travel_delta = (
            initial.utilization_without_travel - baseline.utilization_without_travel
        )
        rows: list[list[object]] = [["Показатель", "Optimized initial", "Baseline", "Разница"]]
        rows.extend(
            [
                [
                    "Назначено",
                    initial.assigned_count,
                    baseline.assigned_count,
                    f"{initial.assigned_count - baseline.assigned_count:+d}",
                ],
                [
                    "Не назначено",
                    initial.unassigned_count,
                    baseline.unassigned_count,
                    f"{initial.unassigned_count - baseline.unassigned_count:+d}",
                ],
                [
                    "Инженеров с маршрутом",
                    initial.engineers_used_count,
                    baseline.engineers_used_count,
                    f"{initial.engineers_used_count - baseline.engineers_used_count:+d}",
                ],
                [
                    "Пробег, км",
                    f"{initial.mileage_km:.2f}",
                    f"{baseline.mileage_km:.2f}",
                    f"{initial.mileage_km - baseline.mileage_km:+.2f}",
                ],
                [
                    "Загрузка с дорогой, %",
                    f"{initial.utilization_with_travel:.2f}",
                    f"{baseline.utilization_with_travel:.2f}",
                    f"{initial.utilization_with_travel - baseline.utilization_with_travel:+.2f}",
                ],
                [
                    "Загрузка без дороги, %",
                    f"{initial.utilization_without_travel:.2f}",
                    f"{baseline.utilization_without_travel:.2f}",
                    f"{without_travel_delta:+.2f}",
                ],
            ]
        )
        return DailyPdfRenderer._table(rows, (38, 22, 20, 20), width, styles)

    @staticmethod
    def _time_utc(value: datetime) -> str:
        return (
            value.replace(tzinfo=UTC)
            .astimezone(ZoneInfo("Europe/Moscow"))
            .strftime("%d.%m.%Y %H:%M")
        )

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
    def _kind_name(kind: PlanKind) -> str:
        match kind:
            case PlanKind.INITIAL:
                return "Исходный"
            case PlanKind.REPLAN:
                return "Перепланирование"
            case PlanKind.EVENT_REPLAN:
                return "По событию"

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
            case UnassignedReason.NO_AVAILABLE_ENGINEER:
                return "Нет доступного инженера"
