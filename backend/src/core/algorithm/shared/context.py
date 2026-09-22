import uuid
from dataclasses import dataclass
from datetime import datetime

from src.config import cfg
from src.core.algorithm.dto import EngineerPlanningContext, TravelMatrix


def engine_priority(db_priority: int) -> int:
    """Переводит приоритет заявки из шкалы БД в вес движка.

    В БД (`Request.priority`, см. `TECHNICAL_CONSTRAINTS.md`) меньше число —
    важнее заявка (1 — авария, 2 — подключение, 3 — ремонт/дозаказ). Движок
    везде **максимизирует** сумму `priority` по маршруту (`route_key`,
    финальный выбор в `LayeredExactStateGraph`, штраф за пропуск заявки в
    OR-Tools) — приоритет должен быть настоящей целью, а не тай-брейком
    после числа заявок, иначе авария может остаться неразмещённой ради
    большего количества менее важных заявок (было известное ограничение, см.
    `docs/ALGORITHM.md`).

    Линейная шкала (`4 - priority` => 3/2/1) этого не гарантирует: три заявки
    тира 3 (сумма 3) перевешивают одну заявку тира 1 (тоже 3) — количество
    побеждает важность. Степенная шкала с настраиваемым основанием
    исключает это: тир 1 всегда даёт вклад на порядки больше, чем любое
    реалистичное количество заявок более низких тиров.
    """
    tier = 4 - db_priority  # 1 (авария) -> 3, 2 (подключение) -> 2, 3 (ремонт/дозаказ) -> 1
    return cfg.algorithm.priority_tier_weight ** (tier - 1)


@dataclass(frozen=True)
class AlgorithmJob:
    """Заявка во внутреннем представлении движка — минуты вместо datetime."""

    request_id: uuid.UUID
    window_start: int
    window_end: int
    service: int
    priority: int


@dataclass(frozen=True)
class AlgorithmContext:
    """Внутренний контекст движка — минуты от полуночи дня смены, доступ к матрице по uuid."""

    jobs: tuple[AlgorithmJob, ...]
    jobs_by_id: dict[uuid.UUID, AlgorithmJob]
    office_id: uuid.UUID
    travel_matrix: TravelMatrix
    shift_start: int
    shift_end: int
    epoch: datetime


def build_context(context: EngineerPlanningContext) -> AlgorithmContext:
    """Строит внутренний `AlgorithmContext` движка из публичного `EngineerPlanningContext`.

    Минуты отсчитываются от полуночи дня начала смены инженера — решение
    рассматривает один рабочий день (см. `SUMMARY.md`), поэтому единый epoch
    для смены и всех окон заявок пула корректен.
    """
    epoch = context.engineer.shift_start.replace(hour=0, minute=0, second=0, microsecond=0)

    def to_minutes(moment: datetime) -> int:
        return int((moment - epoch).total_seconds() // 60)

    jobs = tuple(
        AlgorithmJob(
            request_id=job.id,
            window_start=to_minutes(job.window_start),
            window_end=to_minutes(job.window_end),
            service=job.service_minutes,
            priority=engine_priority(job.priority),
        )
        for job in context.jobs
    )
    return AlgorithmContext(
        jobs=jobs,
        jobs_by_id={job.request_id: job for job in jobs},
        office_id=context.engineer.id,
        travel_matrix=context.travel_matrix,
        shift_start=to_minutes(context.engineer.shift_start),
        shift_end=to_minutes(context.engineer.shift_end),
        epoch=epoch,
    )
