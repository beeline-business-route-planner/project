from collections.abc import Sequence
from contextlib import suppress

from src.config import cfg
from src.core.algorithm.dto import CandidateSelectionResult, RouteCandidate, SelectionKey
from src.core.algorithm.enums import DistributionMode


class _SearchBudgetExhausted(Exception):
    """Внутренний сигнал остановки перебора при исчерпании бюджета узлов."""


class GlobalRouteSelector:
    """Выбирает по одной непересекающейся route column на инженера.

    Branch-and-bound по группам колонок. Поиск стартует с лучшего переданного полного
    решения (incumbent), перебирает колонки от лучших и отсекает ветку, только если её
    покомпонентная верхняя оценка строго хуже текущего лучшего ключа. Пока бюджет узлов
    не исчерпан, результат — точный оптимум по полному ключу решения. При исчерпании
    бюджета возвращается лучшее найденное решение, которое не хуже incumbent; бюджет
    считается в узлах, поэтому результат детерминирован.
    """

    def select(
        self,
        candidate_groups: tuple[tuple[RouteCandidate, ...], ...],
        mode: DistributionMode,
        incumbents: Sequence[tuple[RouteCandidate, ...]] = (),
    ) -> CandidateSelectionResult:
        ordered_groups = tuple(
            tuple(sorted(group, key=self._candidate_order, reverse=True))
            for group in sorted(
                candidate_groups, key=lambda group: (len(group), group[0].engineer_id.int)
            )
        )
        remaining_union = self._remaining_union(ordered_groups)
        best_candidates: tuple[RouteCandidate, ...] = ()
        best_key: SelectionKey | None = None
        for incumbent in incumbents:
            incumbent_key = self._solution_key(incumbent, mode)
            if best_key is None or incumbent_key > best_key:
                best_key = incumbent_key
                best_candidates = incumbent
        visited_nodes_count = 0
        conflict_prunes_count = 0
        bound_prunes_count = 0
        node_budget = cfg.algorithm.selection_node_budget

        def search(
            group_index: int,
            used_mask: int,
            partial: tuple[int, int, int, int],
            service_loads: tuple[int, ...],
            selected: tuple[RouteCandidate, ...],
        ) -> None:
            nonlocal best_candidates
            nonlocal best_key
            nonlocal visited_nodes_count
            nonlocal conflict_prunes_count
            nonlocal bound_prunes_count
            visited_nodes_count += 1
            if visited_nodes_count > node_budget:
                raise _SearchBudgetExhausted
            if group_index == len(ordered_groups):
                candidate_key = self._solution_key(selected, mode)
                if best_key is None or candidate_key > best_key:
                    best_key = candidate_key
                    best_candidates = selected
                return
            if best_key is not None and self._upper_bound(
                ordered_groups[group_index:],
                remaining_union[group_index],
                used_mask,
                partial,
                service_loads,
                mode,
            ) < (
                best_key.priority_score,
                best_key.assigned_count,
                best_key.mode_score,
                best_key.negative_travel_minutes,
            ):
                bound_prunes_count += 1
                return
            priority_score, assigned_count, used_count, travel_minutes = partial
            for candidate in ordered_groups[group_index]:
                if used_mask & candidate.request_mask:
                    conflict_prunes_count += 1
                    continue
                search(
                    group_index + 1,
                    used_mask | candidate.request_mask,
                    (
                        priority_score + candidate.priority_score,
                        assigned_count + len(candidate.request_ids),
                        used_count + bool(candidate.request_ids),
                        travel_minutes + candidate.travel_minutes,
                    ),
                    (*service_loads, candidate.service_minutes),
                    (*selected, candidate),
                )

        with suppress(_SearchBudgetExhausted):
            search(0, 0, (0, 0, 0, 0), (), ())
        return CandidateSelectionResult(
            routes={
                candidate.engineer_id: candidate.request_ids
                for candidate in best_candidates
                if candidate.request_ids
            },
            quality_key=best_key or self._solution_key((), mode),
            visited_nodes_count=min(visited_nodes_count, node_budget),
            conflict_prunes_count=conflict_prunes_count,
            bound_prunes_count=bound_prunes_count,
        )

    @staticmethod
    def _candidate_order(candidate: RouteCandidate) -> tuple[int, int, int]:
        return (
            candidate.priority_score,
            len(candidate.request_ids),
            -candidate.travel_minutes,
        )

    @staticmethod
    def _remaining_union(
        candidate_groups: tuple[tuple[RouteCandidate, ...], ...],
    ) -> tuple[int, ...]:
        unions = [0] * (len(candidate_groups) + 1)
        for index in range(len(candidate_groups) - 1, -1, -1):
            union = unions[index + 1]
            for candidate in candidate_groups[index]:
                union |= candidate.request_mask
            unions[index] = union
        return tuple(unions)

    @staticmethod
    def _upper_bound(
        remaining_groups: tuple[tuple[RouteCandidate, ...], ...],
        remaining_union: int,
        used_mask: int,
        partial: tuple[int, int, int, int],
        service_loads: tuple[int, ...],
        mode: DistributionMode,
    ) -> tuple[int, int, int, int]:
        """Покомпонентная оценка ключа любого завершения частичного выбора.

        Priority и coverage берут максимум по каждой оставшейся группе только среди
        колонок, совместимых с уже занятыми заявками; coverage дополнительно не больше
        числа свободных заявок оставшихся групп. Остальные инженеры могут взять пустую
        колонку, поэтому число задействованных инженеров и дорога не растут, а разброс
        загрузки не меньше текущего.
        """

        priority_score, assigned_count, used_count, travel_minutes = partial
        for group in remaining_groups:
            compatible = [
                candidate for candidate in group if not (candidate.request_mask & used_mask)
            ]
            priority_score += max((candidate.priority_score for candidate in compatible), default=0)
            assigned_count += max(
                (len(candidate.request_ids) for candidate in compatible), default=0
            )
        free_count = (remaining_union & ~used_mask).bit_count()
        assigned_count = min(assigned_count, partial[1] + free_count)
        if mode == DistributionMode.MIN_ENGINEERS:
            mode_score = -used_count
        else:
            mode_score = -(max(service_loads) - min(service_loads)) if service_loads else 0
        return priority_score, assigned_count, mode_score, -travel_minutes

    @staticmethod
    def _solution_key(
        candidates: tuple[RouteCandidate, ...],
        mode: DistributionMode,
    ) -> SelectionKey:
        priority_score = sum(candidate.priority_score for candidate in candidates)
        assigned_count = sum(len(candidate.request_ids) for candidate in candidates)
        used_count = sum(bool(candidate.request_ids) for candidate in candidates)
        travel_minutes = sum(candidate.travel_minutes for candidate in candidates)
        service_loads = [candidate.service_minutes for candidate in candidates]
        load_spread = max(service_loads, default=0) - min(service_loads, default=0)
        mode_score = -used_count if mode == DistributionMode.MIN_ENGINEERS else -load_spread
        tie_breaker = tuple(
            (candidate.engineer_id.int, *(request_id.int for request_id in candidate.request_ids))
            for candidate in sorted(candidates, key=lambda item: item.engineer_id.int)
        )
        return SelectionKey(
            priority_score=priority_score,
            assigned_count=assigned_count,
            mode_score=mode_score,
            negative_travel_minutes=-travel_minutes,
            tie_breaker=tie_breaker,
        )
