from typing import ClassVar

from ortools.constraint_solver import routing_enums_pb2

from src.core.algorithm.contracts import PlanningAlgorithm
from src.core.algorithm.models import EngineerPlanningContext, Route
from src.core.algorithm.shared.comparison import best_route
from src.core.algorithm.shared.context import build_context
from src.core.algorithm.shared.evaluate import materialize_route
from src.core.algorithm.shared.ortools_routing import tuned_ortools_route

_FIRST_SOLUTION_STRATEGIES = (
    routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION,
    routing_enums_pb2.FirstSolutionStrategy.LOCAL_CHEAPEST_INSERTION,
    routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC,
    routing_enums_pb2.FirstSolutionStrategy.SAVINGS,
    routing_enums_pb2.FirstSolutionStrategy.GLOBAL_CHEAPEST_ARC,
)


class OrtoolsMultistartGls(PlanningAlgorithm):
    """4. OR-Tools мультистарт (5 эвристик) + Guided Local Search.

    Дословный перенос `optimized_ortools` из
    `test/algorithms/_shared/engine.py`. Запускает CP Routing
    (`ortools.constraint_solver`) с 5 разными стратегиями первого решения,
    бюджет времени делится поровну между ними, метаэвристика — Guided Local
    Search. Берётся лучший маршрут из пяти по `route_key`.
    """

    name: ClassVar[str] = "OR-Tools мультистарт (5 эвристик) + GLS"
    slug: ClassVar[str] = "ortools_multistart_gls"
    DEFAULT_BUDGET_SECONDS: ClassVar[float] = 5.0

    def plan_initial(self, context: EngineerPlanningContext, budget_seconds: float) -> Route:
        ctx = build_context(context)
        per_run = budget_seconds / len(_FIRST_SOLUTION_STRATEGIES)
        candidates = [
            tuned_ortools_route(ctx, per_run, strategy, use_priority_penalty=False)
            for strategy in _FIRST_SOLUTION_STRATEGIES
        ]
        route = best_route(ctx, candidates)
        return materialize_route(context.engineer.id, ctx, route)
