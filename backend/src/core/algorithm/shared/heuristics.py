import random
import time
import uuid

from src.core.algorithm.shared.comparison import best_route, route_key
from src.core.algorithm.shared.context import _Context
from src.core.algorithm.shared.evaluate import evaluate_route

_EFFICIENT_COMPLETION_MODES = range(3)


def efficient_completion(ctx: _Context, route: list[uuid.UUID], mode: int = 0) -> list[uuid.UUID]:
    """Добавляет оставшиеся заявки по цене дефицитного времени, а не только по приоритету."""
    route = list(route)
    while True:
        assigned = set(route)
        base = evaluate_route(ctx, route)
        candidates = []
        for job in ctx.jobs:
            if job.request_id in assigned:
                continue
            for position in range(len(route) + 1):
                candidate = route[:position] + [job.request_id] + route[position:]
                result = evaluate_route(ctx, candidate)
                if not result.valid:
                    continue
                extra_travel = result.travel - base.travel
                extra_time = job.service + extra_travel
                if mode == 0:
                    choice = (extra_time, job.window_end, -job.priority, result.travel)
                elif mode == 1:
                    choice = (job.window_end, extra_time, -job.priority, result.travel)
                else:
                    choice = (-job.priority, extra_time, job.window_end, result.travel)
                candidates.append((choice, tuple(candidate), candidate))
        if not candidates:
            return route
        route = min(candidates)[-1]


def relocate_descent(ctx: _Context, route: list[uuid.UUID], deadline: float) -> list[uuid.UUID]:
    """Переставляет уже выбранные заявки местами в маршруте, сокращая путь без потери качества."""
    route = list(route)
    while time.perf_counter() < deadline:
        current_key = route_key(ctx, route)
        best = route
        best_key = current_key
        for source in range(len(route)):
            item = route[source]
            shortened = route[:source] + route[source + 1 :]
            for target in range(len(route)):
                if time.perf_counter() >= deadline:
                    return best
                candidate = shortened[:target] + [item] + shortened[target:]
                key = route_key(ctx, candidate)
                if key > best_key:
                    best, best_key = candidate, key
        if best_key <= current_key:
            return route
        route = best
    return route


def ruin_recreate(
    ctx: _Context, route: list[uuid.UUID], seconds: float, seed: int = 42
) -> list[uuid.UUID]:
    """Детерминированный локальный поиск: удаление 1-3 заявок и повторная вставка."""
    rng = random.Random(seed)
    deadline = time.perf_counter() + seconds
    best = relocate_descent(ctx, route, min(deadline, time.perf_counter() + seconds * 0.2))
    iteration = 0
    while time.perf_counter() < deadline and best:
        iteration += 1
        remove_count = 1 + (iteration % min(3, len(best)))
        if iteration % 3 == 0:
            positions = sorted(
                range(len(best)),
                key=lambda i: ctx.jobs_by_id[best[i]].service,
                reverse=True,
            )[:remove_count]
        else:
            positions = rng.sample(range(len(best)), remove_count)
        ruined = [item for i, item in enumerate(best) if i not in set(positions)]
        candidates = [
            efficient_completion(ctx, ruined, mode) for mode in _EFFICIENT_COMPLETION_MODES
        ]
        candidate = best_route(ctx, candidates)
        if route_key(ctx, candidate) > route_key(ctx, best):
            best = candidate
        elif iteration % 7 == 0:
            best = max([best, candidate], key=lambda r: route_key(ctx, r))
    return relocate_descent(ctx, best, deadline)
