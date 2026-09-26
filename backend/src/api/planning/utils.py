from dataclasses import dataclass
from datetime import datetime

from src.api.exc.planning import PlanningFileValidationError
from src.core.db.enums import RequestPriority, RequestTypeBk, Skill


def required_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanningFileValidationError
    return value.strip()


def parse_type_bk(value: object) -> RequestTypeBk:
    mapping = {
        "Глобальная проблема": RequestTypeBk.GLOBAL_PROBLEM,
        "Дозаказ": RequestTypeBk.ADDITIONAL_ORDER,
        "Локальная заявка": RequestTypeBk.LOCAL_REQUEST,
        "Подключение": RequestTypeBk.CONNECTION,
    }
    try:
        return mapping[required_string(value)]
    except KeyError as exc:
        raise PlanningFileValidationError from exc


@dataclass(frozen=True)
class WorkNorm:
    """Норматив выполнения одного типа работы (источник — `Нормативы.xlsx`, см.
    `TECHNICAL_CONSTRAINTS.md`, §2 "Нормативы длительности").

    `total_minutes` включает фиксированную дорожную часть из исходной таблицы
    (везде 20 мин, см. §2 "Норматив включает время дороги"); `service_minutes`
    — то же самое за вычетом неё, чистое время работы у клиента, которое
    используется вместе с расчётным временем маршрута вместо зашитой
    константы.
    """

    total_minutes: int
    travel_minutes: int
    priority: RequestPriority
    required_skill: Skill

    @property
    def service_minutes(self) -> int:
        return self.total_minutes - self.travel_minutes

    def minutes(self, *, with_travel: bool) -> int:
        return self.total_minutes if with_travel else self.service_minutes


def work_norm(type_bk: RequestTypeBk) -> WorkNorm:
    match type_bk:
        case RequestTypeBk.GLOBAL_PROBLEM:
            return WorkNorm(
                total_minutes=100,
                travel_minutes=20,
                priority=RequestPriority.EMERGENCY,
                required_skill=Skill.EMERGENCY_WORKS,
            )
        case RequestTypeBk.CONNECTION:
            return WorkNorm(
                total_minutes=90,
                travel_minutes=20,
                priority=RequestPriority.CONNECTION,
                required_skill=Skill.CONNECTION_AND_ORDERS,
            )
        case RequestTypeBk.ADDITIONAL_ORDER:
            return WorkNorm(
                total_minutes=40,
                travel_minutes=20,
                priority=RequestPriority.REPAIR,
                required_skill=Skill.CONNECTION_AND_ORDERS,
            )
        case RequestTypeBk.LOCAL_REQUEST:
            return WorkNorm(
                total_minutes=50,
                travel_minutes=20,
                priority=RequestPriority.REPAIR,
                required_skill=Skill.LOCAL_WORKS,
            )


def parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(required_string(value), "%d.%m.%Y %H:%M")
    except ValueError as exc:
        raise PlanningFileValidationError from exc
