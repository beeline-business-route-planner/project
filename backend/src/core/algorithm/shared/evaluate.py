import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from src.core.algorithm.models import Route, Stop
from src.core.algorithm.shared.context import _Context


@dataclass(frozen=True)
class _EvaluatedStop:
    request_id: uuid.UUID
    travel: int
    arrival: int
    start: int
    finish: int


@dataclass(frozen=True)
class EvaluationResult:
    """Результат оценки маршрута — минуты внутренние, не `datetime`.

    Дословный перенос словаря, который возвращал `evaluate_route` в
    `test/algorithms/_shared/evaluate.py` — `count`/`priority` обнуляются при
    любом нарушении (нет «частично валидного» маршрута), `finish` — минута
    окончания последней остановки, `occupied` — сумма `service` и `travel`.
    """

    valid: bool
    violations: tuple[str, ...]
    stops: tuple[_EvaluatedStop, ...]
    count: int
    priority: int
    travel: int
    service: int
    finish: int
    occupied: int


def _format_minute(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def evaluate_route(ctx: _Context, route: Sequence[uuid.UUID]) -> EvaluationResult:
    """Проходит маршрут от офиса и проверяет нарушения окна заявки/конца смены.

    Дословный перенос `evaluate_route` — заявка не может начаться раньше
    `window_start` (ожидание допустимо), но обязана начаться не позже
    `window_end`; вся работа обязана закончиться до конца смены.
    """
    current_id = ctx.office_id
    current_time = ctx.shift_start
    total_travel = 0
    total_service = 0
    priority_score = 0
    stops: list[_EvaluatedStop] = []
    violations: list[str] = []
    seen: set[uuid.UUID] = set()
    for request_id in route:
        if request_id in seen:
            violations.append(f"duplicate:{request_id}")
            continue
        seen.add(request_id)
        job = ctx.jobs_by_id[request_id]
        travel = ctx.travel_matrix.minutes(current_id, request_id)
        arrival = current_time + travel
        start = max(arrival, job.window_start)
        finish = start + job.service
        if start > job.window_end:
            violations.append(
                f"late_start:{request_id}:{_format_minute(start)}>{_format_minute(job.window_end)}"
            )
        if finish > ctx.shift_end:
            violations.append(f"after_shift:{request_id}:{_format_minute(finish)}")
        stops.append(_EvaluatedStop(request_id, travel, arrival, start, finish))
        total_travel += travel
        total_service += job.service
        priority_score += job.priority
        current_time = finish
        current_id = request_id
    valid = not violations
    return EvaluationResult(
        valid=valid,
        violations=tuple(violations),
        stops=tuple(stops),
        count=len(route) if valid else 0,
        priority=priority_score if valid else 0,
        travel=total_travel,
        service=total_service,
        finish=current_time,
        occupied=total_service + total_travel,
    )


def independent_audit(ctx: _Context, route: Sequence[uuid.UUID]) -> tuple[str, ...]:
    """Независимая проверка маршрута — пересчитывает результат другим кодом, не `evaluate_route`.

    Не вызывается самими стратегиями — заготовка для последующей проверки
    построенного плана (по аналогии с `test/run_experiments.py::run_one`).
    """
    errors: list[str] = []
    route_list = list(route)
    if len(route_list) != len(set(route_list)):
        errors.append("duplicate request")
    unknown = set(route_list) - set(ctx.jobs_by_id)
    if unknown:
        errors.append(f"unknown requests: {sorted(unknown, key=str)}")
        return tuple(errors)

    clock = ctx.shift_start
    previous = ctx.office_id
    for request_id in route_list:
        job = ctx.jobs_by_id[request_id]
        drive = ctx.travel_matrix.minutes(previous, request_id)
        arrival = clock + drive
        start = arrival if arrival >= job.window_start else job.window_start
        finish = start + job.service
        if start < job.window_start or start > job.window_end:
            errors.append(
                f"{request_id}: start {_format_minute(start)} outside "
                f"{_format_minute(job.window_start)}-{_format_minute(job.window_end)}"
            )
        if finish > ctx.shift_end:
            errors.append(f"{request_id}: finish {_format_minute(finish)} after shift")
        if start < clock + drive:
            errors.append(f"{request_id}: impossible travel")
        clock = finish
        previous = request_id
    return tuple(errors)


def materialize_route(engineer_id: uuid.UUID, ctx: _Context, route: Sequence[uuid.UUID]) -> Route:
    """Строит публичный `Route` (реальные `datetime`/`Decimal`) из маршрута в минутах.

    Второй проход по тем же правилам, что и `evaluate_route`, но с реальными
    датами (`ctx.epoch + timedelta(minutes=...)`) и километрами из
    `TravelMatrix.kilometers` — километры не нужны во время поиска (не влияют
    на `route_key`), поэтому считаются один раз, только для победившего маршрута.
    """
    stops: list[Stop] = []
    current_id = ctx.office_id
    current_minute = ctx.shift_start
    for sequence_number, request_id in enumerate(route, start=1):
        job = ctx.jobs_by_id[request_id]
        travel = ctx.travel_matrix.minutes(current_id, request_id)
        distance = ctx.travel_matrix.kilometers(current_id, request_id)
        arrival_minute = current_minute + travel
        start_minute = max(arrival_minute, job.window_start)
        finish_minute = start_minute + job.service
        stops.append(
            Stop(
                request_id=request_id,
                sequence_number=sequence_number,
                arrival=ctx.epoch + timedelta(minutes=arrival_minute),
                start=ctx.epoch + timedelta(minutes=start_minute),
                finish=ctx.epoch + timedelta(minutes=finish_minute),
                travel_minutes=travel,
                distance_km=distance,
            )
        )
        current_minute = finish_minute
        current_id = request_id
    return Route(engineer_id=engineer_id, stops=tuple(stops))
