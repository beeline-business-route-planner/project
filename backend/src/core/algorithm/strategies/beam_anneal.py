import time
import uuid
from dataclasses import dataclass
from typing import ClassVar

from src.core.algorithm.contracts import PlanningAlgorithm
from src.core.algorithm.models import EngineerPlanningContext, Route
from src.core.algorithm.shared.comparison import route_key
from src.core.algorithm.shared.context import _Context, build_context
from src.core.algorithm.shared.evaluate import materialize_route
from src.core.algorithm.shared.heuristics import ruin_recreate

_BEAM_WIDTH = 500


@dataclass(frozen=True)
class _BeamNode:
    served_mask: int
    last_id: uuid.UUID
    finish: int
    travel: int
    priority: int
    path: tuple[uuid.UUID, ...]


class BeamAnneal(PlanningAlgorithm):
    """6. Приоритетный лучевой поиск (Earliest-Finish-Time-First Beam Search).

    Дословный перенос `my_own_beam_anneal/algorithm.py` из тестового кода.
    Вместо одного жадного пути параллельно ведётся до `_BEAM_WIDTH` частичных
    маршрутов; на каждом шаге кандидаты-продолжения ранжируются по (время
    финиша последней заявки, сумма приоритета, дорога) — раньше
    освобождаешься — больше остаётся слота под будущие заявки, при равном
    финише выигрывает больший приоритет. После луча — adjacent-swap (обмен
    двух соседних заявок, если это не портит валидность и сокращает дорогу),
    затем весь оставшийся бюджет отдаётся под Ruin-and-Recreate.
    """

    name: ClassVar[str] = "Приоритетный лучевой поиск (Claude, Earliest-Finish-Time beam)"
    slug: ClassVar[str] = "beam_anneal"
    DEFAULT_BUDGET_SECONDS: ClassVar[float] = 3.0

    def plan_initial(self, context: EngineerPlanningContext, budget_seconds: float) -> Route:
        ctx = build_context(context)
        deadline = time.perf_counter() + budget_seconds
        route = self._beam_search(ctx, deadline)
        route = self._adjacent_swap_polish(ctx, route, deadline)
        remaining = max(0.0, deadline - time.perf_counter())
        if remaining > 0:
            polished = ruin_recreate(ctx, route, remaining, seed=2026)
            if route_key(ctx, polished) > route_key(ctx, route):
                route = polished
        return materialize_route(context.engineer.id, ctx, route)

    def _beam_search(self, ctx: _Context, deadline: float) -> list[uuid.UUID]:
        beams = [_BeamNode(0, ctx.office_id, ctx.shift_start, 0, 0, ())]
        best_final = beams[0]

        while time.perf_counter() < deadline:
            candidates: dict[int, _BeamNode] = {}
            expanded_any = False
            for node in beams:
                for i, job in enumerate(ctx.jobs):
                    bit = 1 << i
                    if node.served_mask & bit:
                        continue
                    drive = ctx.travel_matrix.minutes(node.last_id, job.request_id)
                    start = max(node.finish + drive, job.window_start)
                    finish = start + job.service
                    if start > job.window_end or finish > ctx.shift_end:
                        continue
                    expanded_any = True
                    new_mask = node.served_mask | bit
                    candidate = _BeamNode(
                        new_mask,
                        job.request_id,
                        finish,
                        node.travel + drive,
                        node.priority + job.priority,
                        node.path + (job.request_id,),
                    )
                    existing = candidates.get(new_mask)
                    key = (candidate.priority, -candidate.travel, -candidate.finish)
                    if existing is None or key > (
                        existing.priority,
                        -existing.travel,
                        -existing.finish,
                    ):
                        candidates[new_mask] = candidate
                if node.path and (len(node.path), node.priority, -node.travel) > (
                    len(best_final.path),
                    best_final.priority,
                    -best_final.travel,
                ):
                    best_final = node

            if not expanded_any:
                break

            def rank(node: _BeamNode) -> tuple[int, int, int]:
                return (node.finish, -node.priority, node.travel)

            ranked = sorted(candidates.values(), key=rank)
            beams = ranked[:_BEAM_WIDTH]

        for node in beams:
            if node.path and (
                (len(node.path), node.priority, -node.travel)
                > (len(best_final.path), best_final.priority, -best_final.travel)
            ):
                best_final = node

        return list(best_final.path)

    def _adjacent_swap_polish(
        self, ctx: _Context, route: list[uuid.UUID], deadline: float
    ) -> list[uuid.UUID]:
        route = list(route)
        improved = True
        while improved and time.perf_counter() < deadline:
            improved = False
            for i in range(len(route) - 1):
                swapped = route[:i] + [route[i + 1], route[i]] + route[i + 2 :]
                if route_key(ctx, swapped) > route_key(ctx, route):
                    route = swapped
                    improved = True
        return route
