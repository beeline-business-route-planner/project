from datetime import datetime

from src.api.planning.service_exc import PlanningFileValidationError
from src.core.db.enums import RequestTypeBk, Skill


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


def request_rules(type_bk: RequestTypeBk) -> tuple[int, int, int, Skill]:
    return {
        RequestTypeBk.GLOBAL_PROBLEM: (100, 80, 1, Skill.EMERGENCY_WORKS),
        RequestTypeBk.CONNECTION: (90, 70, 2, Skill.CONNECTION_AND_ORDERS),
        RequestTypeBk.ADDITIONAL_ORDER: (40, 20, 3, Skill.CONNECTION_AND_ORDERS),
        RequestTypeBk.LOCAL_REQUEST: (50, 30, 3, Skill.LOCAL_WORKS),
    }[type_bk]


def parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(required_string(value), "%d.%m.%Y %H:%M")
    except ValueError as exc:
        raise PlanningFileValidationError from exc
