import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from src.core.db.enums import Region, Skill, UnassignedReason, VehicleType


@dataclass(frozen=True)
class Job:
    """Заявка на уровне алгоритма — проекция `Request` без ORM.

    `id` совпадает с `Request.id` и одновременно служит ключом узла в
    `TravelMatrix` — стратегиям не нужен отдельный маппинг заявка → индекс.
    """

    id: uuid.UUID
    latitude: Decimal
    longitude: Decimal
    window_start: datetime
    window_end: datetime
    service_minutes: int
    priority: int
    required_skill: Skill
    required_vehicle_type: VehicleType | None


@dataclass(frozen=True)
class EngineerContext:
    """Инженер на уровне алгоритма — проекция `Engineer` без ORM.

    `id` также используется как ключ стартовой точки маршрута в `TravelMatrix`.
    """

    id: uuid.UUID
    start_latitude: Decimal
    start_longitude: Decimal
    shift_start: datetime
    shift_end: datetime
    skills: frozenset[Skill]
    vehicle_type: VehicleType


class TravelMatrix(Protocol):
    """Матрица времени/расстояния между точками.

    Реализуется вне пакета `algorithm` (см. `docs/ALGORITHM.md`, будущий
    `src/core/routing/`) — стратегии знают только про этот протокол, не про
    конкретного провайдера (OSRM/2ГИС), поэтому их можно тестировать на
    фейковой матрице без сети.
    """

    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int: ...

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal: ...


@dataclass(frozen=True)
class EngineerPlanningContext:
    """Всё, что нужно стратегии для построения маршрута одного инженера.

    `jobs` — пул заявок, уже отфильтрованный `DistributionPlanner`-ом по
    навыку/транспорту/округу (см. `docs/ALGORITHM.md`, "Пул допустимых
    заявок"). Стратегия сама решает, сколько из них поместится по факту
    окон/смены/матрицы.
    """

    engineer: EngineerContext
    jobs: tuple[Job, ...]
    travel_matrix: TravelMatrix


@dataclass(frozen=True)
class Stop:
    """Одна остановка построенного маршрута — заготовка будущего `PlanStop`."""

    request_id: uuid.UUID
    sequence_number: int
    arrival: datetime
    start: datetime
    finish: datetime
    travel_minutes: int
    distance_km: Decimal


@dataclass(frozen=True)
class Route:
    """Результат работы стратегии для одного инженера."""

    engineer_id: uuid.UUID
    stops: tuple[Stop, ...]

    @property
    def assigned_job_ids(self) -> frozenset[uuid.UUID]:
        """Id заявок маршрута — `DistributionPlanner` вычитает их из пулов остальных инженеров."""
        return frozenset(stop.request_id for stop in self.stops)


@dataclass(frozen=True)
class AlgorithmPlanResult:
    """Результат `AlgorithmService.plan_initial` — сводка по сохранённому `Plan`."""

    plan_id: uuid.UUID
    region: Region
    engineers_used_count: int
    total_mileage_km: Decimal
    assigned_requests_count: int
    unassigned_requests_count: int


@dataclass(frozen=True)
class UnassignedJob:
    """Заявка, которую не удалось разместить ни у одного инженера, и причина."""

    job_id: uuid.UUID
    reason: UnassignedReason


@dataclass(frozen=True)
class DistributionResult:
    """Результат распределения пула заявок округа между всеми его инженерами."""

    routes: tuple[Route, ...]
    unassigned: tuple[UnassignedJob, ...]
