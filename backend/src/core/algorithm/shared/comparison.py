import uuid
from collections.abc import Sequence

from src.core.algorithm.shared.context import _Context
from src.core.algorithm.shared.evaluate import evaluate_route

RouteKey = tuple[int, int, int, int]

_INVALID_KEY: RouteKey = (-1, -1, -(10**9), -(10**9))


def route_key(ctx: _Context, route: Sequence[uuid.UUID]) -> RouteKey:
    """Лексикографический критерий качества маршрута: заявки → приоритет → -дорога → -финиш."""
    result = evaluate_route(ctx, route)
    if not result.valid:
        return _INVALID_KEY
    return (result.count, result.priority, -result.travel, -result.finish)


def best_route(ctx: _Context, routes: Sequence[Sequence[uuid.UUID]]) -> list[uuid.UUID]:
    """Выбирает лучший маршрут из набора кандидатов по `route_key`."""
    best = routes[0]
    best_key = route_key(ctx, best)
    for candidate in routes[1:]:
        candidate_key = route_key(ctx, candidate)
        if candidate_key > best_key:
            best, best_key = candidate, candidate_key
    return list(best)
