"""Deterministic external adapters and input books for planning E2E scenarios."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from src.api.planning.dto import PlanningUploadFile
from src.core.dgis.service import DgisMatrix
from src.core.geocoding.dto import Coordinates
from src.core.travel_matrix import TravelMatrixUnavailableError

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

    async def build(self, points: list, requests: list) -> list[DgisMatrix]:
        matrices = []
        indexes = {point.id: index for index, point in enumerate(points)}
        size = len(points)
        for _ in requests:
            self.calls += 1
            if self.calls == self.fail_on_call:
                raise TravelMatrixUnavailableError("Синтетический сбой маршрутизации")
            matrices.append(
                DgisMatrix(
                    indexes,
                    [[0 if row == col else 5 for col in range(size)] for row in range(size)],
                    [
                        [Decimal(0) if row == col else Decimal(1) for col in range(size)]
                        for row in range(size)
                    ],
                )
            )
        return matrices


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
