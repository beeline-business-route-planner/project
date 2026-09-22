import time
import uuid
from typing import ClassVar

from src.config import cfg
from src.core.algorithm.contracts import PlanningAlgorithm
from src.core.algorithm.dto import EngineerPlanningContext, Route
from src.core.algorithm.shared.comparison import best_route
from src.core.algorithm.shared.context import AlgorithmContext, build_context
from src.core.algorithm.shared.evaluate import evaluate_route, materialize_route
from src.core.algorithm.shared.heuristics import efficient_completion, ruin_recreate


class RegretInsertionRuinRecreate(PlanningAlgorithm):
    """3. Regret-вставка + Ruin-and-Recreate.

    Дословный перенос `optimized_greedy`/`regret_insertion` из
    `test/algorithms/_shared/engine.py`. Строит маршрут через регрет-2
    вставку (штраф за то, что заявка не вставлена сейчас — насколько хуже
    станет её лучшая позиция позже), достраивает каждый вариант
    (`efficient_completion`) и полирует лучший результат Ruin-and-Recreate.
    Фаза вставки жёстко ограничена 60% бюджета, оставшиеся 40% гарантированно
    достаются полировке (санкционированное отклонение от исходного топ-5, см.
    докстринг в оригинале).
    """

    name: ClassVar[str] = "Regret-вставка + Ruin-and-Recreate"
    slug: ClassVar[str] = "regret_insertion_ruin_recreate"

    @property
    def default_budget_seconds(self) -> float:
        return cfg.algorithm.regret_budget_seconds

    def plan_initial(self, context: EngineerPlanningContext, budget_seconds: float) -> Route:
        started = time.perf_counter()
        ctx = build_context(context)
        insertion_deadline = started + budget_seconds * 0.6
        seeds: list[list[uuid.UUID]] = []
        for variant in range(cfg.algorithm.regret_variant_count):
            if time.perf_counter() >= insertion_deadline:
                break
            seed_route = self._regret_insertion(ctx, variant, deadline=insertion_deadline)
            seeds.extend(efficient_completion(ctx, seed_route, mode) for mode in range(3))
        if not seeds:
            seeds = [[]]
        best = best_route(ctx, seeds)
        remaining = max(0.0, budget_seconds - (time.perf_counter() - started))
        route = ruin_recreate(ctx, best, remaining, seed=73)
        return materialize_route(context.engineer.id, ctx, route)

    def _regret_insertion(
        self, ctx: AlgorithmContext, variant: int, deadline: float
    ) -> list[uuid.UUID]:
        route: list[uuid.UUID] = []
        remaining = {job.request_id for job in ctx.jobs}
        while True:
            if time.perf_counter() >= deadline:
                return route
            base = evaluate_route(ctx, route)
            job_choices = []
            for job in ctx.jobs:
                if job.request_id not in remaining:
                    continue
                placements = []
                for position in range(len(route) + 1):
                    candidate = route[:position] + [job.request_id] + route[position:]
                    result = evaluate_route(ctx, candidate)
                    if result.valid:
                        placements.append(
                            (
                                result.travel - base.travel,
                                result.finish,
                                tuple(candidate),
                                candidate,
                            )
                        )
                if not placements:
                    continue
                placements.sort()
                best_cost = placements[0][0]
                second_cost = placements[1][0] if len(placements) > 1 else best_cost + 60
                regret = second_cost - best_cost
                key: tuple[int, ...]
                if variant == 0:
                    key = (job.window_end, job.service, -regret, best_cost, -job.priority)
                elif variant == 1:
                    key = (job.service, job.window_end, -regret, best_cost, -job.priority)
                elif variant == 2:
                    key = (-regret, job.window_end, job.service, best_cost, -job.priority)
                elif variant == 3:
                    key = (-job.priority, -regret, job.window_end, best_cost)
                elif variant == 4:
                    key = (job.window_end - job.window_start, -regret, best_cost, -job.priority)
                else:
                    key = (best_cost, -regret, job.window_end, -job.priority)
                job_choices.append((key, placements[0][-1], job.request_id))
            if not job_choices:
                return route
            _, route, chosen = min(job_choices)
            remaining.remove(chosen)
