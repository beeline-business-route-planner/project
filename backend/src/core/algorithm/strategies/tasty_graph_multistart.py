import time
import uuid
from typing import ClassVar

from src.core.algorithm.contracts import PlanningAlgorithm
from src.core.algorithm.models import EngineerPlanningContext, Route
from src.core.algorithm.shared.comparison import best_route
from src.core.algorithm.shared.context import _Context, build_context
from src.core.algorithm.shared.evaluate import evaluate_route, materialize_route
from src.core.algorithm.shared.heuristics import efficient_completion, ruin_recreate

_WEIGHT_SETS: tuple[tuple[float, float, float, float], ...] = (
    (1.0, 1.0, 1.0, 25.0),
    (1.0, 0.5, 1.3, 10.0),
    (1.5, 0.2, 1.0, 15.0),
    (0.8, 1.5, 1.2, 5.0),
    (2.0, 0.1, 1.5, 20.0),
)


class TastyGraphMultistart(PlanningAlgorithm):
    """2. Мультистартовый «вкусный граф» + Ruin-and-Recreate.

    Дословный перенос `optimized_global`/`append_variant` из
    `test/algorithms/_shared/engine.py`. Стоимость следующей вставки —
    взвешенная сумма (дорога, ожидание, длительность работы, штраф за
    приоритет) с 5 наборами весов; каждый жадный маршрут достраивается
    (`efficient_completion`), лучший вариант полируется Ruin-and-Recreate.
    """

    name: ClassVar[str] = "Мультистартовый «вкусный граф» + Ruin-and-Recreate"
    slug: ClassVar[str] = "tasty_graph_multistart"
    DEFAULT_BUDGET_SECONDS: ClassVar[float] = 3.0

    def plan_initial(self, context: EngineerPlanningContext, budget_seconds: float) -> Route:
        started = time.perf_counter()
        ctx = build_context(context)
        seeds: list[list[uuid.UUID]] = []
        for weights in _WEIGHT_SETS:
            base = self._append_variant(ctx, weights)
            seeds.extend(efficient_completion(ctx, base, mode) for mode in range(3))
        best = best_route(ctx, seeds)
        remaining = max(0.0, budget_seconds - (time.perf_counter() - started))
        route = ruin_recreate(ctx, best, remaining)
        return materialize_route(context.engineer.id, ctx, route)

    def _append_variant(
        self, ctx: _Context, weights: tuple[float, float, float, float]
    ) -> list[uuid.UUID]:
        travel_w, wait_w, service_w, priority_w = weights
        route: list[uuid.UUID] = []
        remaining = {job.request_id for job in ctx.jobs}
        while True:
            base = evaluate_route(ctx, route)
            choices = []
            for job in ctx.jobs:
                if job.request_id not in remaining:
                    continue
                result = evaluate_route(ctx, route + [job.request_id])
                if not result.valid:
                    continue
                stop = result.stops[-1]
                extra_travel = result.travel - base.travel
                wait = stop.start - stop.arrival
                value = (
                    travel_w * extra_travel
                    + wait_w * wait
                    + service_w * job.service
                    - priority_w * job.priority
                )
                choices.append((value, job.window_end, job.request_id))
            if not choices:
                return route
            chosen = min(choices)[2]
            route.append(chosen)
            remaining.remove(chosen)
