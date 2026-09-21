import uuid
from dataclasses import dataclass
from typing import ClassVar

from src.core.algorithm.contracts import PlanningAlgorithm
from src.core.algorithm.models import EngineerPlanningContext, Route
from src.core.algorithm.shared.context import _Context, build_context
from src.core.algorithm.shared.evaluate import materialize_route


@dataclass(frozen=True)
class _BeamState:
    mask: int
    last_id: uuid.UUID
    finish: int
    travel: int
    priority: int
    path: tuple[uuid.UUID, ...]


class LayeredExactStateGraph(PlanningAlgorithm):
    """1. Послойный точный граф состояний.

    Дословный перенос `bounded_state_graph` из
    `test/algorithms/_shared/engine.py` — точная динамика по временным слоям
    окон заявок с Парето-доминированием состояний (последняя точка, время
    окончания, дорога, приоритет). Доказанно оптимален только когда окна
    заявок идут непересекающимися слоями по `window_start` (см.
    `docs/ALGORITHM.md`, "Известные ограничения") — при пересекающихся окнах
    доминирование между "слоями" перестаёт быть точным.

    Единственное изменение относительно оригинала — не логика, а формат
    данных: узел "OFFICE" — не строковый sentinel с отдельным индексом в
    матрице, а `context.engineer.id` напрямую, так как `TravelMatrix`
    адресуется по uuid, а не по позиционному индексу (index_by_id и
    travel_matrix-как-список-списков из оригинала не нужны вовсе).
    """

    name: ClassVar[str] = "Послойный точный граф состояний"
    slug: ClassVar[str] = "layered_exact_state_graph"
    DEFAULT_BUDGET_SECONDS: ClassVar[float] = 3.0

    def plan_initial(self, context: EngineerPlanningContext, budget_seconds: float) -> Route:
        # Бюджет не расходуется — точный алгоритм, не итеративный поиск
        # (оригинал тоже игнорировал seconds/beam_width, см. докстринг там).
        del budget_seconds
        ctx = build_context(context)
        route = self._bounded_state_graph(ctx)
        return materialize_route(context.engineer.id, ctx, route)

    def _bounded_state_graph(self, ctx: _Context) -> list[uuid.UUID]:
        def add_pareto(labels: list[_BeamState], candidate: _BeamState) -> None:
            if any(
                state.finish <= candidate.finish and state.travel <= candidate.travel
                for state in labels
            ):
                return
            labels[:] = [
                state
                for state in labels
                if not (candidate.finish <= state.finish and candidate.travel <= state.travel)
            ]
            labels.append(candidate)

        states = [_BeamState(0, ctx.office_id, ctx.shift_start, 0, 0, ())]
        for window_start in sorted({job.window_start for job in ctx.jobs}):
            bucket = [i for i, job in enumerate(ctx.jobs) if job.window_start == window_start]
            all_states = list(states)
            frontier = [
                _BeamState(0, state.last_id, state.finish, state.travel, state.priority, state.path)
                for state in states
            ]
            for _ in range(len(bucket)):
                labels: dict[tuple[int, uuid.UUID, int, int], list[_BeamState]] = {}
                for state in frontier:
                    for local_position, nxt in enumerate(bucket):
                        if state.mask & (1 << local_position):
                            continue
                        job = ctx.jobs[nxt]
                        drive = ctx.travel_matrix.minutes(state.last_id, job.request_id)
                        start = max(state.finish + drive, job.window_start)
                        finish = start + job.service
                        if start > job.window_end or finish > ctx.shift_end:
                            continue
                        candidate = _BeamState(
                            state.mask | (1 << local_position),
                            job.request_id,
                            finish,
                            state.travel + drive,
                            state.priority + job.priority,
                            state.path + (job.request_id,),
                        )
                        signature = (
                            candidate.mask,
                            candidate.last_id,
                            len(candidate.path),
                            candidate.priority,
                        )
                        add_pareto(labels.setdefault(signature, []), candidate)
                frontier = [state for group in labels.values() for state in group]
                all_states.extend(frontier)
                if not frontier:
                    break

            by_last: dict[uuid.UUID, list[_BeamState]] = {}
            ordered = sorted(
                all_states,
                key=lambda state: (
                    -len(state.path),
                    -state.priority,
                    state.finish,
                    state.travel,
                ),
            )
            for candidate in ordered:
                bucket_labels = by_last.setdefault(candidate.last_id, [])
                candidate_count = len(candidate.path)
                if any(
                    len(state.path) >= candidate_count
                    and state.priority >= candidate.priority
                    and state.finish <= candidate.finish
                    and state.travel <= candidate.travel
                    for state in bucket_labels
                ):
                    continue
                bucket_labels[:] = [
                    state
                    for state in bucket_labels
                    if not (
                        candidate_count >= len(state.path)
                        and candidate.priority >= state.priority
                        and candidate.finish <= state.finish
                        and candidate.travel <= state.travel
                    )
                ]
                bucket_labels.append(
                    _BeamState(
                        0,
                        candidate.last_id,
                        candidate.finish,
                        candidate.travel,
                        candidate.priority,
                        candidate.path,
                    )
                )
            states = [state for group in by_last.values() for state in group]

        best = max(
            states,
            key=lambda state: (len(state.path), state.priority, -state.travel, -state.finish),
        )
        return list(best.path)
