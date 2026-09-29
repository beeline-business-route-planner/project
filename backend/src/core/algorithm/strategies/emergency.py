import uuid
from dataclasses import dataclass
from datetime import datetime

from src.config import cfg
from src.core.algorithm.dto import Engineer, InitialPlanningInput, Job, PlanningLayer
from src.core.algorithm.materialization import ScheduleMaterializer
from src.core.algorithm.rules import PlanningRules


@dataclass(frozen=True)
class _EmergencyState:
    finish: datetime
    travel_minutes: int
    request_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class _EmergencyRoute:
    """Лучший найденный порядок одного набора аварий у одной бригады."""

    mask: int
    travel_minutes: int
    request_ids: tuple[uuid.UUID, ...]


@dataclass(slots=True)
class _PackingSearch:
    """Состояние перебора: лучшее найденное распределение наборов аварий по бригадам."""

    order: tuple[tuple[int, tuple[int, ...]], ...]
    tables: tuple[dict[int, _EmergencyRoute], ...]
    capacities: tuple[dict[int, int], ...]
    twins: tuple[tuple[int, ...], ...]
    budget: list[int]
    best_count: int = -1
    best_masks: tuple[int, ...] = ()


class _StateBudgetExhausted(Exception):
    """Внутренний сигнал: точная фаза вышла за детерминированный бюджет."""


class EmergencyPlanner:
    """Назначает максимально возможное число аварий в их SLA, не глядя на остальные заявки.

    Для каждой бригады динамика по состояниям «набор аварий, последняя авария» хранит самое
    раннее окончание (при равенстве — меньшую дорогу): раннее окончание никогда не мешает
    продолжению, поэтому множество достижимых наборов найдено точно. Затем branch-and-bound
    распределяет аварии по бригадам с максимумом назначенных. Дорогу фаза не оптимизирует.
    Результат — только аварийные маршруты; стратегия дозаполняет их сама. При
    превышении `emergency_phase_state_budget` фаза детерминированно не выполняется.
    """

    def __init__(self) -> None:
        self._materializer = ScheduleMaterializer()

    def assign(
        self, planning_input: InitialPlanningInput
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]] | None:
        emergencies = tuple(job for job in planning_input.jobs if job.is_emergency)
        if not emergencies:
            return None
        jobs_by_id = {job.id: job for job in planning_input.jobs}
        layers_by_request = PlanningRules.index_layers(planning_input.layers, jobs_by_id)
        engineers = sorted(
            (engineer for engineer in planning_input.engineers if engineer.is_available),
            key=lambda engineer: engineer.id.int,
        )
        budget = [cfg.algorithm.emergency_phase_state_budget]
        try:
            routes_by_engineer: list[tuple[uuid.UUID, dict[int, _EmergencyRoute]]] = [
                (
                    engineer.id,
                    self._engineer_routes(
                        engineer,
                        emergencies,
                        jobs_by_id,
                        layers_by_request,
                        planning_input.calculation_cutoff_at,
                        budget,
                    ),
                )
                for engineer in engineers
            ]
            masks = self._pack(emergencies, engineers, routes_by_engineer, budget)
        except _StateBudgetExhausted:
            return None
        return {
            engineer_id: routes[mask].request_ids
            for (engineer_id, routes), mask in zip(routes_by_engineer, masks, strict=True)
            if mask
        }

    def _engineer_routes(
        self,
        engineer: Engineer,
        emergencies: tuple[Job, ...],
        jobs_by_id: dict[uuid.UUID, Job],
        layers_by_request: dict[uuid.UUID, PlanningLayer],
        cutoff_at: datetime,
        budget: list[int],
    ) -> dict[int, _EmergencyRoute]:
        eligible = [
            (1 << position, job)
            for position, job in enumerate(emergencies)
            if PlanningRules.eligible(engineer, job)
        ]
        frontier = {(0, engineer.id): _EmergencyState(engineer.available_from, 0, ())}
        best_by_mask: dict[int, _EmergencyRoute] = {}
        while frontier:
            extended: dict[tuple[int, uuid.UUID], _EmergencyState] = {}
            for (mask, _), state in frontier.items():
                for bit, job in eligible:
                    if mask & bit:
                        continue
                    request_ids = (*state.request_ids, job.id)
                    stops = self._materializer.materialize(
                        engineer, request_ids, jobs_by_id, layers_by_request, cutoff_at
                    )
                    if stops is None:
                        continue
                    budget[0] -= 1
                    if budget[0] < 0:
                        raise _StateBudgetExhausted
                    candidate = _EmergencyState(
                        stops[-1].finish,
                        state.travel_minutes + stops[-1].travel_minutes,
                        request_ids,
                    )
                    key = (mask | bit, job.id)
                    kept = extended.get(key)
                    if kept is None or (candidate.finish, candidate.travel_minutes) < (
                        kept.finish,
                        kept.travel_minutes,
                    ):
                        extended[key] = candidate
            for (mask, _), state in extended.items():
                current = best_by_mask.get(mask)
                if current is None or state.travel_minutes < current.travel_minutes:
                    best_by_mask[mask] = _EmergencyRoute(
                        mask, state.travel_minutes, state.request_ids
                    )
            frontier = extended
        return best_by_mask

    def _pack(
        self,
        emergencies: tuple[Job, ...],
        engineers: list[Engineer],
        routes_by_engineer: list[tuple[uuid.UUID, dict[int, _EmergencyRoute]]],
        budget: list[int],
    ) -> tuple[int, ...]:
        """Branch-and-bound: каждая авария — одной бригаде (если набор достижим) или никому.

        Самые срочные аварии идут первыми; ветка отсекается, если даже все оставшиеся
        аварии не дают больше уже найденного числа.

        Returns:
            Маску аварий каждой бригады в порядке `routes_by_engineer`.
        """

        order = tuple(
            (
                1 << position,
                tuple(
                    engineer_index
                    for engineer_index, engineer in enumerate(engineers)
                    if PlanningRules.eligible(engineer, job)
                ),
            )
            for position, job in sorted(
                enumerate(emergencies),
                key=lambda item: (item[1].latest_start_at, item[1].id.int),
            )
        )
        tables = tuple(routes for _, routes in routes_by_engineer)
        search = _PackingSearch(
            order=order,
            tables=tables,
            capacities=tuple(self._capacities(table) for table in tables),
            twins=tuple(
                tuple(
                    earlier
                    for earlier in range(engineer_index)
                    if tables[earlier].keys() == table.keys()
                )
                for engineer_index, table in enumerate(tables)
            ),
            budget=budget,
        )
        self._branch(search, 0, (0,) * len(engineers), 0)
        return search.best_masks

    @staticmethod
    def _capacities(table: dict[int, _EmergencyRoute]) -> dict[int, int]:
        """Сколько аварий бригада ещё может добавить к каждому своему достижимому набору."""

        capacities = {0: max((mask.bit_count() for mask in table), default=0)}
        for mask in table:
            capacities[mask] = (
                max(other.bit_count() for other in table if other & mask == mask) - mask.bit_count()
            )
        return capacities

    def _branch(
        self, search: _PackingSearch, index: int, masks: tuple[int, ...], count: int
    ) -> None:
        search.budget[0] -= 1
        if search.budget[0] < 0:
            raise _StateBudgetExhausted
        capacity = sum(
            engineer_capacities[mask]
            for engineer_capacities, mask in zip(search.capacities, masks, strict=True)
        )
        if count + min(len(search.order) - index, capacity) <= search.best_count:
            return
        if index == len(search.order):
            search.best_count, search.best_masks = count, masks
            return
        bit, engineer_indexes = search.order[index]
        for engineer_index in engineer_indexes:
            # Бригады с одинаковыми достижимыми наборами взаимозаменяемы: из пустых
            # берётся только первая.
            if not masks[engineer_index] and any(
                not masks[twin] for twin in search.twins[engineer_index]
            ):
                continue
            extended = masks[engineer_index] | bit
            if extended in search.tables[engineer_index]:
                self._branch(
                    search,
                    index + 1,
                    (*masks[:engineer_index], extended, *masks[engineer_index + 1 :]),
                    count + 1,
                )
        self._branch(search, index + 1, masks, count)
