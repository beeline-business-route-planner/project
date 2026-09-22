import uuid
from typing import ClassVar

from ortools.constraint_solver import routing_enums_pb2

from src.config import cfg
from src.core.algorithm.contracts import PlanningAlgorithm
from src.core.algorithm.dto import EngineerPlanningContext, Route
from src.core.algorithm.shared.comparison import best_route
from src.core.algorithm.shared.context import build_context
from src.core.algorithm.shared.evaluate import materialize_route
from src.core.algorithm.shared.ortools_routing import tuned_ortools_route
from src.core.algorithm.strategies.layered_exact_state_graph import LayeredExactStateGraph
from src.core.algorithm.strategies.ortools_multistart_gls import OrtoolsMultistartGls
from src.core.algorithm.strategies.regret_insertion_ruin_recreate import (
    RegretInsertionRuinRecreate,
)
from src.core.algorithm.strategies.tasty_graph_multistart import TastyGraphMultistart


class HybridSeedOrtoolsPolish(PlanningAlgorithm):
    """5. Гибрид: посев из четырёх алгоритмов + OR-Tools GLS-полировка.

    Дословный перенос `optimized_hybrid` из `test/algorithms/_shared/engine.py`
    — лучший из четырёх посевных маршрутов отдаётся в OR-Tools как стартовое
    решение, дальше OR-Tools улучшает его локальным поиском (Guided Local
    Search). Бюджеты посевов урезаны вдвое от штатных (см. оригинальный
    докстринг: гибрид ни разу не обошёл лучший из своих посевов по числу
    заявок/приоритету на прогоне 001, поэтому платить временем за улучшение,
    которого не происходит на практике, не имеет смысла).

    Единственное разрешённое исключение из изоляции стратегий друг от друга
    (см. `docs/ALGORITHM.md`) — этот алгоритм по своей природе берёт
    результаты четырёх остальных (`TastyGraphMultistart`,
    `RegretInsertionRuinRecreate`, `LayeredExactStateGraph`,
    `OrtoolsMultistartGls`) как посев. Остальные пять стратегий друг от
    друга не зависят.
    """

    name: ClassVar[str] = "Гибрид: посев (4 алгоритма) + OR-Tools GLS-полировка"
    slug: ClassVar[str] = "hybrid_seed_ortools_polish"

    @property
    def default_budget_seconds(self) -> float:
        return cfg.algorithm.hybrid_budget_seconds

    def plan_initial(self, context: EngineerPlanningContext, budget_seconds: float) -> Route:
        ctx = build_context(context)
        seed_routes = (
            TastyGraphMultistart().plan_initial(context, cfg.algorithm.hybrid_seed_budget_seconds),
            RegretInsertionRuinRecreate().plan_initial(
                context, cfg.algorithm.hybrid_seed_budget_seconds
            ),
            LayeredExactStateGraph().plan_initial(
                context, cfg.algorithm.hybrid_seed_budget_seconds
            ),
            OrtoolsMultistartGls().plan_initial(
                context, cfg.algorithm.hybrid_ortools_seed_budget_seconds
            ),
        )
        seeds: list[list[uuid.UUID]] = [
            [stop.request_id for stop in route.stops] for route in seed_routes
        ]
        seed = best_route(ctx, seeds)
        improved = tuned_ortools_route(
            ctx,
            budget_seconds,
            routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION,
            initial_route=seed,
        )
        route = best_route(ctx, [seed, improved])
        return materialize_route(context.engineer.id, ctx, route)
