"""Визуальные блоки PDF-отчётов: тема, KPI-карточки, диаграммы и таймлайны на ReportLab."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Literal

from reportlab.lib import colors
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable

ASSETS = Path(__file__).parent / "assets"

FONT = "Onest"
FONT_MEDIUM = "Onest-Medium"
FONT_SEMIBOLD = "Onest-SemiBold"
FONT_BOLD = "Onest-Bold"

YELLOW = colors.HexColor("#FFD400")
YELLOW_SOFT = colors.HexColor("#FFF4BF")
INK = colors.HexColor("#1D1E22")
INK_SOFT = colors.HexColor("#45474F")
MUTED = colors.HexColor("#83868E")
LINE = colors.HexColor("#E7E5DF")
SURFACE = colors.HexColor("#F6F5F1")
TEAL = colors.HexColor("#1FB5A6")
TEAL_SOFT = colors.HexColor("#D8F3F0")
IDLE = colors.HexColor("#E9E7E1")
GOOD = colors.HexColor("#1E9B60")
GOOD_SOFT = colors.HexColor("#DDF3E7")
BAD = colors.HexColor("#D8473E")
BAD_MILD = colors.HexColor("#F2A7A1")
BAD_SOFT = colors.HexColor("#FBE3E1")
NEUTRAL_SOFT = colors.HexColor("#ECEBE7")
WHITE = colors.white

Better = Literal["higher", "lower"] | None


def register_fonts() -> None:
    registered = pdfmetrics.getRegisteredFontNames()
    for name, file in (
        (FONT, "Onest-Regular.ttf"),
        (FONT_MEDIUM, "Onest-Medium.ttf"),
        (FONT_SEMIBOLD, "Onest-SemiBold.ttf"),
        (FONT_BOLD, "Onest-Bold.ttf"),
    ):
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(ASSETS / file)))
    pdfmetrics.registerFontFamily(
        FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD
    )


def fmt_number(value: float, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text.replace("-", "−")


def fmt_signed(value: float, digits: int = 0) -> str:
    if round(value, digits) == 0:
        return fmt_number(0, digits)
    return ("+" if value > 0 else "") + fmt_number(value, digits)


def fmt_duration(minutes: int) -> str:
    hours, rest = divmod(max(minutes, 0), 60)
    if not hours:
        return f"{rest} мин"
    return f"{hours} ч {rest:02d} мин" if rest else f"{hours} ч"


def text_width(text: str, font: str, size: float) -> float:
    return float(pdfmetrics.stringWidth(text, font, size))


def fit_text(text: str, font: str, size: float, width: float) -> str:
    if text_width(text, font, size) <= width:
        return text
    while text and text_width(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def delta_tone(delta: float, better: Better) -> tuple[Color, Color]:
    if better is None or delta == 0:
        return INK_SOFT, NEUTRAL_SOFT
    good = delta > 0 if better == "higher" else delta < 0
    return (GOOD, GOOD_SOFT) if good else (BAD, BAD_SOFT)


def draw_pill(
    canvas: Canvas, x: float, y: float, text: str, fg: Color, bg: Color, size: float = 7.5
) -> float:
    """Рисует плашку с левым нижним углом в (x, y) и возвращает её ширину."""
    width = text_width(text, FONT_SEMIBOLD, size) + 12
    height = size + 7
    canvas.setFillColor(bg)
    canvas.roundRect(x, y, width, height, height / 2, stroke=0, fill=1)
    canvas.setFillColor(fg)
    canvas.setFont(FONT_SEMIBOLD, size)
    canvas.drawString(x + 6, y + 4.2, text)
    return width


class Block(Flowable):
    """Flowable фиксированной ширины и высоты: наследники рисуют в draw()."""

    def __init__(self, width: float, height: float) -> None:
        super().__init__()
        self.width = width
        self.height = height

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:  # noqa: N803
        return self.width, self.height


class Hero(Block):
    """Шапка отчёта: крупный заголовок, подзаголовок, статус дня и метаданные."""

    def __init__(
        self, width: float, title: str, subtitle: str, status: tuple[str, bool], meta: str
    ) -> None:
        super().__init__(width, 84)
        self.title = title
        self.subtitle = subtitle
        self.status = status
        self.meta = meta

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(YELLOW)
        c.rect(0, 14, 5, 66, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(FONT_BOLD, 28)
        c.drawString(16, 50, self.title)
        c.setFont(FONT_MEDIUM, 12)
        c.setFillColor(INK_SOFT)
        c.drawString(16, 30, self.subtitle)
        label, in_progress = self.status
        pill_x = 16 + text_width(self.subtitle, FONT_MEDIUM, 12) + 10
        fg, bg = (INK, YELLOW) if in_progress else (GOOD, GOOD_SOFT)
        draw_pill(c, pill_x, 27.5, label, fg, bg, 8)
        c.setFont(FONT, 8)
        c.setFillColor(MUTED)
        c.drawString(16, 14, self.meta)


class SectionTitle(Block):
    def __init__(self, width: float, title: str, hint: str | None = None) -> None:
        super().__init__(width, 34 if hint else 26)
        self.title = title
        self.hint = hint

    def draw(self) -> None:
        c = self.canv
        top = self.height
        c.setFillColor(YELLOW)
        c.roundRect(0, top - 17, 4, 13, 1.5, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(FONT_SEMIBOLD, 13)
        c.drawString(11, top - 15, self.title)
        if self.hint:
            c.setFont(FONT, 8)
            c.setFillColor(MUTED)
            c.drawString(11, top - 28, self.hint)


@dataclass(frozen=True)
class Kpi:
    label: str
    value: str
    note: str = ""
    accent: bool = False
    unit: str = ""


class KpiCards(Block):
    def __init__(self, width: float, cards: Sequence[Kpi], gap: float = 10) -> None:
        super().__init__(width, 76)
        self.cards = cards
        self.gap = gap

    def draw(self) -> None:
        c = self.canv
        count = len(self.cards)
        card_width = (self.width - self.gap * (count - 1)) / count
        for index, card in enumerate(self.cards):
            x = index * (card_width + self.gap)
            c.setFillColor(YELLOW if card.accent else SURFACE)
            c.roundRect(x, 0, card_width, self.height, 10, stroke=0, fill=1)
            c.setFillColor(INK if card.accent else MUTED)
            c.setFont(FONT_MEDIUM, 8)
            c.drawString(x + 12, self.height - 19, card.label)
            c.setFillColor(INK)
            c.setFont(FONT_BOLD, 24)
            c.drawString(x + 12, 24, card.value)
            if card.unit:
                c.setFont(FONT_SEMIBOLD, 11)
                gap = 1.5 if card.unit == "%" else 4
                c.drawString(x + 12 + gap + text_width(card.value, FONT_BOLD, 24), 24, card.unit)
            if card.note:
                c.setFont(FONT, 7.5)
                c.setFillColor(INK_SOFT)
                c.drawString(x + 12, 10, fit_text(card.note, FONT, 7.5, card_width - 24))


@dataclass(frozen=True)
class CompareRow:
    label: str
    current: float
    reference: float
    digits: int = 0
    unit: str = ""
    better: Better = None


class ComparisonBars(Block):
    """Пары полос «текущее / эталон» с цветной плашкой изменения."""

    ROW = 33

    def __init__(
        self,
        width: float,
        rows: Sequence[CompareRow],
        legend: tuple[str, str] = ("Оптимизированный", "Baseline"),
    ) -> None:
        super().__init__(width, 20 + len(rows) * self.ROW)
        self.rows = rows
        self.legend = legend

    def draw(self) -> None:
        c = self.canv
        label_width = min(135.0, self.width * 0.34)
        chip_width = 62.0
        bar_left = label_width
        value_width = max(
            text_width(fmt_number(value, row.digits) + row.unit, FONT_SEMIBOLD, 7.5)
            for row in self.rows
            for value in (row.current, row.reference)
        )
        bar_width = self.width - label_width - chip_width - value_width - 16
        self._legend(c)
        for index, row in enumerate(self.rows):
            y = self.height - 20 - (index + 1) * self.ROW
            c.setFillColor(INK_SOFT)
            c.setFont(FONT_MEDIUM, 8.5)
            c.drawString(0, y + 13, fit_text(row.label, FONT_MEDIUM, 8.5, label_width - 8))
            scale = max(abs(row.current), abs(row.reference), 1e-9)
            for offset, value, color in ((17, row.current, YELLOW), (6, row.reference, IDLE)):
                c.setFillColor(SURFACE)
                c.roundRect(bar_left, y + offset, bar_width, 8, 2.5, stroke=0, fill=1)
                c.setFillColor(color)
                length = max(bar_width * abs(value) / scale, 2)
                c.roundRect(bar_left, y + offset, length, 8, 2.5, stroke=0, fill=1)
                c.setFillColor(INK if color is YELLOW else MUTED)
                c.setFont(FONT_SEMIBOLD if color is YELLOW else FONT, 7.5)
                c.drawString(
                    bar_left + bar_width + 5,
                    y + offset + 1,
                    fmt_number(value, row.digits) + row.unit,
                )
            delta = round(row.current - row.reference, row.digits)
            fg, bg = delta_tone(delta, row.better)
            arrow = "↑ " if delta > 0 else "↓ " if delta < 0 else ""
            text = arrow + fmt_number(abs(delta), row.digits) if delta else "0"
            chip = text_width(text, FONT_SEMIBOLD, 7.5) + 12
            draw_pill(c, self.width - chip, y + 9, text, fg, bg)
            c.setStrokeColor(LINE)
            c.setLineWidth(0.5)
            c.line(0, y, self.width, y)

    def _legend(self, c: Canvas) -> None:
        x = 0.0
        for label, color in zip(self.legend, (YELLOW, IDLE), strict=True):
            c.setFillColor(color)
            c.roundRect(x, self.height - 10, 10, 7, 2, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.setFont(FONT, 7.5)
            c.drawString(x + 14, self.height - 9.5, label)
            x += 24 + text_width(label, FONT, 7.5)


@dataclass(frozen=True)
class Segment:
    label: str
    value: float
    color: Color
    caption: str = ""


class Donut(Block):
    """Кольцевая диаграмма с подписью в центре и легендой справа."""

    def __init__(
        self, width: float, segments: Sequence[Segment], center: str, center_note: str
    ) -> None:
        super().__init__(width, 150)
        self.segments = segments
        self.center = center
        self.center_note = center_note

    def draw(self) -> None:
        c = self.canv
        radius = 62.0
        cx, cy = radius + 6, self.height / 2
        total = sum(max(segment.value, 0) for segment in self.segments)
        angle = 90.0
        c.setStrokeColor(WHITE)
        c.setLineWidth(1.5)
        if total <= 0:
            c.setFillColor(IDLE)
            c.circle(cx, cy, radius, stroke=0, fill=1)
        for segment in self.segments:
            if total <= 0 or segment.value <= 0:
                continue
            extent = -360.0 * segment.value / total
            c.setFillColor(segment.color)
            c.wedge(
                cx - radius, cy - radius, cx + radius, cy + radius, angle, extent, stroke=1, fill=1
            )
            angle += extent
        c.setFillColor(WHITE)
        c.circle(cx, cy, radius * 0.62, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(FONT_BOLD, 17)
        c.drawCentredString(cx, cy - 1, self.center)
        c.setFont(FONT, 7)
        c.setFillColor(MUTED)
        c.drawCentredString(cx, cy - 13, self.center_note)
        self._legend(c, cx + radius + 22, total)

    def _legend(self, c: Canvas, x: float, total: float) -> None:
        row = 34.0
        y = self.height / 2 + row * (len(self.segments) - 1) / 2
        for segment in self.segments:
            share = segment.value / total * 100 if total else 0
            c.setFillColor(segment.color)
            c.roundRect(x, y + 1, 9, 9, 2, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont(FONT_SEMIBOLD, 9)
            c.drawString(x + 15, y + 2, f"{segment.label}  {fmt_number(share)}%")
            if segment.caption:
                c.setFont(FONT, 7.5)
                c.setFillColor(MUTED)
                c.drawString(x + 15, y - 9, segment.caption)
            y -= row


@dataclass(frozen=True)
class Bar:
    label: str
    value: float
    color: Color = YELLOW


class HorizontalBars(Block):
    ROW = 22

    def __init__(
        self, width: float, bars: Sequence[Bar], value_text: Callable[[float], str]
    ) -> None:
        super().__init__(width, max(len(bars), 1) * self.ROW)
        self.bars = bars
        self.value_text = value_text

    def draw(self) -> None:
        c = self.canv
        label_width = min(170.0, self.width * 0.42)
        bar_width = self.width - label_width - 40
        top = max((bar.value for bar in self.bars), default=0) or 1
        for index, bar in enumerate(self.bars):
            y = self.height - (index + 1) * self.ROW + 6
            c.setFont(FONT_MEDIUM, 8.5)
            c.setFillColor(INK_SOFT)
            c.drawString(0, y + 1, fit_text(bar.label, FONT_MEDIUM, 8.5, label_width - 8))
            c.setFillColor(SURFACE)
            c.roundRect(label_width, y, bar_width, 10, 3, stroke=0, fill=1)
            c.setFillColor(bar.color)
            c.roundRect(
                label_width, y, max(bar_width * bar.value / top, 3), 10, 3, stroke=0, fill=1
            )
            c.setFillColor(INK)
            c.setFont(FONT_SEMIBOLD, 8.5)
            c.drawString(label_width + bar_width + 6, y + 1, self.value_text(bar.value))


@dataclass(frozen=True)
class TimelineStop:
    sequence: int
    arrival: datetime
    start: datetime
    finish: datetime
    travel_minutes: int


@dataclass(frozen=True)
class TimelineRow:
    name: str
    shift_start: datetime
    shift_end: datetime
    available: bool
    utilization: float
    stops: tuple[TimelineStop, ...]


class ShiftTimeline(Block):
    """Гант смены: дорога, ожидание и работа по каждому инженеру на общей оси времени."""

    ROW = 19
    AXIS = 26
    NAME = 128.0
    UTIL = 74.0

    def __init__(self, width: float, rows: Sequence[TimelineRow], hours: tuple[int, int]) -> None:
        super().__init__(width, self.AXIS + len(rows) * self.ROW + 22)
        self.rows = rows
        self.first_hour, self.last_hour = hours
        day = rows[0].shift_start.date() if rows else datetime.min.date()
        self.origin = datetime.combine(day, time()) + timedelta(hours=self.first_hour)

    def _x(self, value: datetime) -> float:
        span = (self.last_hour - self.first_hour) * 60
        minutes = (value - self.origin).total_seconds() / 60
        track = self.width - self.NAME - self.UTIL
        return self.NAME + track * min(max(minutes / span, 0), 1)

    def draw(self) -> None:
        c = self.canv
        self._axis(c)
        for index, row in enumerate(self.rows):
            y = self.height - self.AXIS - (index + 1) * self.ROW
            if index % 2 == 0:
                c.setFillColor(SURFACE)
                c.rect(0, y, self.width, self.ROW, stroke=0, fill=1)
            self._row(c, row, y)
        self._legend(c)

    def _axis(self, c: Canvas) -> None:
        top = self.height - self.AXIS
        bottom = 22
        for hour in range(self.first_hour, self.last_hour + 1):
            x = self._x(self.origin + timedelta(hours=hour - self.first_hour))
            c.setStrokeColor(LINE)
            c.setLineWidth(0.5)
            c.line(x, bottom, x, top + 4)
            c.setFont(FONT_MEDIUM, 7.5)
            c.setFillColor(MUTED)
            c.drawCentredString(x, top + 8, f"{hour % 24:02d}:00")
        c.setFont(FONT_MEDIUM, 7.5)
        c.drawString(4, top + 8, "Инженер")
        c.drawRightString(self.width - 4, top + 8, "Загрузка")

    def _row(self, c: Canvas, row: TimelineRow, y: float) -> None:
        mid = y + self.ROW / 2
        c.setFont(FONT_MEDIUM, 8)
        c.setFillColor(INK if row.available else MUTED)
        c.drawString(4, mid - 3, fit_text(row.name, FONT_MEDIUM, 8, self.NAME - 10))
        left, right = self._x(row.shift_start), self._x(row.shift_end)
        c.setFillColor(IDLE if row.available else NEUTRAL_SOFT)
        c.roundRect(left, mid - 5, right - left, 10, 3, stroke=0, fill=1)
        if not row.available:
            c.setFont(FONT, 7)
            c.setFillColor(MUTED)
            c.drawCentredString((left + right) / 2, mid - 2.5, "Недоступен")
        for stop in row.stops:
            arrival = self._x(stop.arrival)
            travel_left = max(arrival - self._travel_width(stop.travel_minutes), left)
            c.setFillColor(TEAL)
            c.rect(travel_left, mid - 5, arrival - travel_left, 10, stroke=0, fill=1)
            start, finish = self._x(stop.start), self._x(stop.finish)
            c.setFillColor(YELLOW)
            c.setStrokeColor(WHITE)
            c.setLineWidth(0.6)
            c.rect(start, mid - 5, finish - start, 10, stroke=1, fill=1)
            if finish - start >= 10:
                c.setFillColor(INK)
                c.setFont(FONT_SEMIBOLD, 6.5)
                c.drawCentredString((start + finish) / 2, mid - 2.3, str(stop.sequence))
        self._utilization(c, row, mid)

    def _travel_width(self, minutes: int) -> float:
        track = self.width - self.NAME - self.UTIL
        return track * minutes / ((self.last_hour - self.first_hour) * 60)

    def _utilization(self, c: Canvas, row: TimelineRow, mid: float) -> None:
        x = self.width - self.UTIL + 10
        bar = self.UTIL - 44
        share = min(max(row.utilization / 100, 0), 1)
        c.setFillColor(IDLE)
        c.roundRect(x, mid - 2.5, bar, 5, 2.5, stroke=0, fill=1)
        c.setFillColor(INK_SOFT if row.available else MUTED)
        if share > 0:
            c.roundRect(x, mid - 2.5, max(bar * share, 5), 5, 2.5, stroke=0, fill=1)
        c.setFont(FONT_SEMIBOLD, 7.5)
        c.setFillColor(INK)
        c.drawRightString(self.width - 4, mid - 2.8, f"{fmt_number(row.utilization)}%")

    def _legend(self, c: Canvas) -> None:
        x = self.NAME
        for label, color in (
            ("Работа на заявке (номер остановки)", YELLOW),
            ("Дорога", TEAL),
            ("Свободное время смены", IDLE),
        ):
            c.setFillColor(color)
            c.roundRect(x, 4, 12, 8, 2, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.setFont(FONT, 7.5)
            c.drawString(x + 16, 5, label)
            x += 34 + text_width(label, FONT, 7.5)


@dataclass(frozen=True)
class TimelineEntry:
    time: str
    title: str
    detail: str
    color: Color
    chips: tuple[tuple[str, Color, Color], ...] = ()


class TimelineItem(Block):
    """Один пункт хронологии дня; соседние пункты соединяются вертикальной линией."""

    def __init__(self, width: float, entry: TimelineEntry, first: bool, last: bool) -> None:
        super().__init__(width, 40)
        self.entry = entry
        self.first = first
        self.last = last

    def draw(self) -> None:
        c = self.canv
        dot_x, dot_y = 72.0, self.height - 13
        c.setStrokeColor(LINE)
        c.setLineWidth(1.5)
        c.line(
            dot_x, 0 if not self.last else dot_y, dot_x, self.height if not self.first else dot_y
        )
        c.setFillColor(WHITE)
        c.circle(dot_x, dot_y, 6, stroke=0, fill=1)
        c.setFillColor(self.entry.color)
        c.circle(dot_x, dot_y, 4.2, stroke=0, fill=1)
        c.setFillColor(INK_SOFT)
        c.setFont(FONT_SEMIBOLD, 9)
        c.drawRightString(dot_x - 14, dot_y - 3, self.entry.time)
        x = dot_x + 16
        c.setFillColor(INK)
        c.setFont(FONT_SEMIBOLD, 9.5)
        c.drawString(x, dot_y - 3.5, self.entry.title)
        chip_x = x + text_width(self.entry.title, FONT_SEMIBOLD, 9.5) + 10
        for text, fg, bg in self.entry.chips:
            chip_x += draw_pill(c, chip_x, dot_y - 7, text, fg, bg, 7) + 5
        c.setFont(FONT, 8)
        c.setFillColor(MUTED)
        c.drawString(x, dot_y - 17, fit_text(self.entry.detail, FONT, 8, self.width - x))


@dataclass(frozen=True)
class RegionCard:
    name: str
    assigned: int
    requests: int
    rows: tuple[tuple[str, str], ...]


class RegionCards(Block):
    def __init__(self, width: float, cards: Sequence[RegionCard], gap: float = 12) -> None:
        super().__init__(width, 60 + 17 * max((len(card.rows) for card in cards), default=0))
        self.cards = cards
        self.gap = gap

    def draw(self) -> None:
        c = self.canv
        count = max(len(self.cards), 3)
        card_width = (self.width - self.gap * (count - 1)) / count
        for index, card in enumerate(self.cards):
            x = index * (card_width + self.gap)
            c.saveState()
            outline = c.beginPath()
            outline.roundRect(x, 0, card_width, self.height, 10)
            c.clipPath(outline, stroke=0, fill=0)
            c.setFillColor(SURFACE)
            c.rect(x, 0, card_width, self.height, stroke=0, fill=1)
            c.setFillColor(YELLOW)
            c.rect(x, self.height - 5, card_width, 5, stroke=0, fill=1)
            c.restoreState()
            c.setFillColor(INK)
            c.setFont(FONT_SEMIBOLD, 12)
            c.drawString(x + 14, self.height - 25, card.name)
            coverage = card.assigned / card.requests if card.requests else 0
            c.setFont(FONT, 8)
            c.setFillColor(MUTED)
            c.drawRightString(
                x + card_width - 14,
                self.height - 25,
                f"{card.assigned} из {card.requests} · {fmt_number(coverage * 100)}%",
            )
            bar_y = self.height - 40
            c.setFillColor(IDLE)
            c.roundRect(x + 14, bar_y, card_width - 28, 6, 3, stroke=0, fill=1)
            c.setFillColor(YELLOW)
            c.roundRect(x + 14, bar_y, max((card_width - 28) * coverage, 6), 6, 3, stroke=0, fill=1)
            y = bar_y - 19
            for label, value in card.rows:
                c.setFont(FONT, 8.5)
                c.setFillColor(INK_SOFT)
                c.drawString(x + 14, y, label)
                c.setFont(FONT_SEMIBOLD, 8.5)
                c.setFillColor(INK)
                c.drawRightString(x + card_width - 14, y, value)
                y -= 17


class EngineerHeader(Block):
    """Шапка маршрута инженера с ключевыми цифрами в плашках."""

    def __init__(
        self,
        width: float,
        name: str,
        chips: Sequence[str],
        utilization: float,
        available: bool,
    ) -> None:
        super().__init__(width, 44)
        self.name = name
        self.chips = chips
        self.utilization = utilization
        self.available = available

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(SURFACE)
        c.roundRect(0, 0, self.width, self.height, 9, stroke=0, fill=1)
        c.setFillColor(YELLOW if self.available else IDLE)
        c.circle(20, self.height / 2, 10, stroke=0, fill=1)
        initials = "".join(part[:1] for part in self.name.split()[:2]).upper()
        c.setFillColor(INK)
        c.setFont(FONT_BOLD, 8)
        c.drawCentredString(20, self.height / 2 - 3, initials)
        c.setFont(FONT_SEMIBOLD, 11)
        c.drawString(38, self.height / 2 + 3, self.name)
        x = 38.0
        for chip in self.chips:
            c.setFont(FONT, 7.5)
            c.setFillColor(MUTED)
            c.drawString(x, self.height / 2 - 11, chip)
            x += text_width(chip, FONT, 7.5) + 14
        if not self.available:
            draw_pill(
                c,
                38 + text_width(self.name, FONT_SEMIBOLD, 11) + 8,
                self.height / 2 + 0.5,
                "Недоступен",
                BAD,
                BAD_SOFT,
                7,
            )
        bar = 110.0
        x = self.width - bar - 58
        c.setFont(FONT, 7.5)
        c.setFillColor(MUTED)
        c.drawString(x, self.height / 2 + 5, "Загрузка с дорогой")
        c.setFillColor(IDLE)
        c.roundRect(x, self.height / 2 - 8, bar, 6, 3, stroke=0, fill=1)
        share = min(max(self.utilization / 100, 0), 1)
        if share > 0:
            c.setFillColor(YELLOW)
            c.roundRect(x, self.height / 2 - 8, max(bar * share, 6), 6, 3, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(FONT_BOLD, 13)
        c.drawRightString(self.width - 12, self.height / 2 - 9, f"{fmt_number(self.utilization)}%")


class Note(Block):
    """Спокойная плашка-заглушка для пустых разделов."""

    def __init__(
        self, width: float, text: str, tone: Literal["neutral", "good"] = "neutral"
    ) -> None:
        super().__init__(width, 30)
        self.text = text
        self.tone = tone

    def draw(self) -> None:
        c = self.canv
        good = self.tone == "good"
        c.setFillColor(GOOD_SOFT if good else SURFACE)
        c.roundRect(0, 0, self.width, self.height, 8, stroke=0, fill=1)
        c.setFillColor(GOOD if good else INK_SOFT)
        c.setFont(FONT_MEDIUM, 9)
        c.drawString(14, 11, ("✓  " if good else "") + self.text)


@dataclass(frozen=True)
class StackedRow:
    label: str
    segments: tuple[Segment, ...]
    total_text: str


class StackedBars(Block):
    """Горизонтальные 100%-полосы: доли сегментов по каждой строке."""

    ROW = 30

    def __init__(self, width: float, rows: Sequence[StackedRow]) -> None:
        super().__init__(width, 18 + len(rows) * self.ROW)
        self.rows = rows

    def draw(self) -> None:
        c = self.canv
        label_width = 135.0
        total_width = 70.0
        bar_width = self.width - label_width - total_width
        if self.rows:
            self._legend(c, self.rows[0].segments)
        for index, row in enumerate(self.rows):
            y = self.height - 18 - (index + 1) * self.ROW + 8
            c.setFont(FONT_MEDIUM, 8.5)
            c.setFillColor(INK_SOFT)
            c.drawString(0, y + 4, fit_text(row.label, FONT_MEDIUM, 8.5, label_width - 8))
            total = sum(max(segment.value, 0) for segment in row.segments)
            x = label_width
            c.setFillColor(SURFACE)
            c.roundRect(x, y, bar_width, 14, 3, stroke=0, fill=1)
            for segment in row.segments:
                if total <= 0 or segment.value <= 0:
                    continue
                length = bar_width * segment.value / total
                c.setFillColor(segment.color)
                c.setStrokeColor(WHITE)
                c.setLineWidth(1)
                c.rect(x, y, length, 14, stroke=1, fill=1)
                share = f"{fmt_number(segment.value / total * 100)}%"
                if length > text_width(share, FONT_SEMIBOLD, 7.5) + 8:
                    c.setFillColor(INK)
                    c.setFont(FONT_SEMIBOLD, 7.5)
                    c.drawCentredString(x + length / 2, y + 4, share)
                x += length
            c.setFont(FONT, 8)
            c.setFillColor(MUTED)
            c.drawRightString(self.width, y + 4, row.total_text)

    def _legend(self, c: Canvas, segments: Sequence[Segment]) -> None:
        x = 0.0
        for segment in segments:
            c.setFillColor(segment.color)
            c.roundRect(x, self.height - 10, 10, 7, 2, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.setFont(FONT, 7.5)
            c.drawString(x + 14, self.height - 9.5, segment.label)
            x += 24 + text_width(segment.label, FONT, 7.5)
