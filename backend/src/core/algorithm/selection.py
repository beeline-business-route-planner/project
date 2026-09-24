from src.core.algorithm.dto import CandidateSelectionResult, RouteCandidate, SelectionKey
from src.core.algorithm.enums import DistributionMode


class GlobalRouteSelector:
    """Выбирает по одной непересекающейся route column на инженера."""

    def select(
        self,
        candidate_groups: tuple[tuple[RouteCandidate, ...], ...],
        mode: DistributionMode,
    ) -> CandidateSelectionResult:
        ordered_groups = tuple(
            sorted(candidate_groups, key=lambda group: (len(group), group[0].engineer_id.int))
        )
        max_remaining_priority, max_remaining_count = self._remaining_bounds(ordered_groups)
        best_candidates: tuple[RouteCandidate, ...] = ()
        best_key: SelectionKey | None = None
        visited_nodes_count = 0
        conflict_prunes_count = 0
        bound_prunes_count = 0

        def search(
            group_index: int,
            used_mask: int,
            priority_score: int,
            assigned_count: int,
            selected: tuple[RouteCandidate, ...],
        ) -> None:
            nonlocal best_candidates
            nonlocal best_key
            nonlocal visited_nodes_count
            nonlocal conflict_prunes_count
            nonlocal bound_prunes_count
            visited_nodes_count += 1
            if self._cannot_beat_best(
                group_index,
                priority_score,
                assigned_count,
                max_remaining_priority,
                max_remaining_count,
                best_key,
            ):
                bound_prunes_count += 1
                return
            if group_index == len(ordered_groups):
                candidate_key = self._solution_key(selected, mode)
                if best_key is None or candidate_key > best_key:
                    best_key = candidate_key
                    best_candidates = selected
                return
            for candidate in ordered_groups[group_index]:
                if used_mask & candidate.request_mask:
                    conflict_prunes_count += 1
                    continue
                search(
                    group_index + 1,
                    used_mask | candidate.request_mask,
                    priority_score + candidate.priority_score,
                    assigned_count + len(candidate.request_ids),
                    (*selected, candidate),
                )

        search(0, 0, 0, 0, ())
        return CandidateSelectionResult(
            routes={
                candidate.engineer_id: candidate.request_ids
                for candidate in best_candidates
                if candidate.request_ids
            },
            quality_key=best_key or self._solution_key((), mode),
            visited_nodes_count=visited_nodes_count,
            conflict_prunes_count=conflict_prunes_count,
            bound_prunes_count=bound_prunes_count,
        )

    @staticmethod
    def _remaining_bounds(
        candidate_groups: tuple[tuple[RouteCandidate, ...], ...],
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        priorities = [0] * (len(candidate_groups) + 1)
        counts = [0] * (len(candidate_groups) + 1)
        for index in range(len(candidate_groups) - 1, -1, -1):
            priorities[index] = priorities[index + 1] + max(
                candidate.priority_score for candidate in candidate_groups[index]
            )
            counts[index] = counts[index + 1] + max(
                len(candidate.request_ids) for candidate in candidate_groups[index]
            )
        return tuple(priorities), tuple(counts)

    @staticmethod
    def _cannot_beat_best(
        group_index: int,
        priority_score: int,
        assigned_count: int,
        max_remaining_priority: tuple[int, ...],
        max_remaining_count: tuple[int, ...],
        best_key: SelectionKey | None,
    ) -> bool:
        if best_key is None:
            return False
        priority_upper_bound = priority_score + max_remaining_priority[group_index]
        if priority_upper_bound != best_key.priority_score:
            return priority_upper_bound < best_key.priority_score
        count_upper_bound = assigned_count + max_remaining_count[group_index]
        return count_upper_bound < best_key.assigned_count

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
