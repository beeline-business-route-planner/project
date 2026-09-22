import uuid
from collections.abc import Sequence

from src.core.algorithm.shared.context import AlgorithmContext
from src.core.algorithm.shared.evaluate import evaluate_route

type RouteKey = tuple[int, int, int, int]


def route_key(ctx: AlgorithmContext, route: Sequence[uuid.UUID]) -> RouteKey:
    """Лексикографический критерий качества маршрута: приоритет → заявки → -дорога → -финиш.

    Приоритет — первый критерий, не тай-брейк после числа заявок: маршрут с
    более важными заявками (см. степенную шкалу `engine_priority`) всегда
    предпочтительнее маршрута с большим числом менее важных, даже если
    последний закрывает больше заявок. Число заявок — второй критерий,
    решает только между маршрутами с одинаковой суммой приоритета.
    """
    result = evaluate_route(ctx, route)
    if not result.valid:
        return (-1, -1, -(10**9), -(10**9))
    return (result.priority, result.count, -result.travel, -result.finish)


def best_route(ctx: AlgorithmContext, routes: Sequence[Sequence[uuid.UUID]]) -> list[uuid.UUID]:
    """Выбирает лучший маршрут из набора кандидатов по `route_key`."""
    best = routes[0]
    best_key = route_key(ctx, best)
    for candidate in routes[1:]:
        candidate_key = route_key(ctx, candidate)
        if candidate_key > best_key:
            best, best_key = candidate, candidate_key
    return list(best)
