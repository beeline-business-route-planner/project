import uuid
from dataclasses import dataclass
from datetime import datetime

from src.core.algorithm.models import EngineerPlanningContext, TravelMatrix


def _engine_priority(db_priority: int) -> int:
    """Переводит приоритет заявки из шкалы БД в шкалу движка.

    В БД (`Request.priority`, см. `TECHNICAL_CONSTRAINTS.md`) меньше число —
    важнее заявка (1 — авария). Перенесённый из `test/algorithms/` движок
    работает в обратной шкале (`test/data/loader.py::TYPE_PRIORITY`: авария —
    3, подключение — 2, ремонт/дозаказ — 1) и везде **максимизирует** сумму
    `priority` по маршруту (`route_key`, штраф за пропуск заявки в OR-Tools).
    Скормить приоритет из БД без инверсии — значит заставить движок
    предпочитать маршруты с большим числом неважных заявок вместо аварийных.
    `4 - priority` при `priority` в [1, 3] (см. `ck_request_priority`) зеркалит
    ровно ту же раскладку, что и `TYPE_PRIORITY`, не меняя логику самого движка.
    """
    return 4 - db_priority


@dataclass(frozen=True)
class _Job:
    """Заявка во внутреннем представлении движка — минуты вместо datetime."""

    request_id: uuid.UUID
    window_start: int
    window_end: int
    service: int
    priority: int


@dataclass
class _Context:
    """Внутренний контекст движка — минуты от полуночи дня смены, доступ к матрице по uuid."""

    jobs: list[_Job]
    jobs_by_id: dict[uuid.UUID, _Job]
    office_id: uuid.UUID
    travel_matrix: TravelMatrix
    shift_start: int
    shift_end: int
    epoch: datetime


def build_context(context: EngineerPlanningContext) -> _Context:
    """Строит внутренний `_Context` движка из публичного `EngineerPlanningContext`.

    Минуты отсчитываются от полуночи дня начала смены инженера — решение
    рассматривает один рабочий день (см. `SUMMARY.md`), поэтому единый epoch
    для смены и всех окон заявок пула корректен.
    """
    epoch = context.engineer.shift_start.replace(hour=0, minute=0, second=0, microsecond=0)

    def to_minutes(moment: datetime) -> int:
        return int((moment - epoch).total_seconds() // 60)

    jobs = [
        _Job(
            request_id=job.id,
            window_start=to_minutes(job.window_start),
            window_end=to_minutes(job.window_end),
            service=job.service_minutes,
            priority=_engine_priority(job.priority),
        )
        for job in context.jobs
    ]
    return _Context(
        jobs=jobs,
        jobs_by_id={job.request_id: job for job in jobs},
        office_id=context.engineer.id,
        travel_matrix=context.travel_matrix,
        shift_start=to_minutes(context.engineer.shift_start),
        shift_end=to_minutes(context.engineer.shift_end),
        epoch=epoch,
    )
