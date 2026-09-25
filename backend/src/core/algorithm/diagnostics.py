import uuid
from collections.abc import Callable
from datetime import datetime
from time import perf_counter_ns

from src.core.algorithm.dto import (
    LayerDiagnostics,
    LnsSearchDiagnostics,
    SelectionDiagnostics,
    StrategyDiagnostics,
)


class AlgorithmDiagnostics:
    """Изменяемый сборщик одного прогона, изолированный от сохраняемого результата."""

    def __init__(self, clock_ns: Callable[[], int] = perf_counter_ns) -> None:
        self._clock_ns = clock_ns
        self._total_started_at = 0
        self._stage_started_at = 0
        self._assignment_ns = 0
        self._result_build_ns = 0
        self._audit_ns = 0
        self._selection_ns = 0
        self._selection_runs_count = 0
        self._selection_candidate_routes_count = 0
        self._selection_visited_nodes_count = 0
        self._selection_conflict_prunes_count = 0
        self._selection_bound_prunes_count = 0
        self._graph_runs_count = 0
        self._lns_search: LnsSearchDiagnostics | None = None
        self._layers: list[LayerDiagnostics] = []

    def start(self) -> None:
        started_at = self._clock_ns()
        self._total_started_at = started_at
        self._stage_started_at = started_at

    def finish_assignment(self) -> None:
        finished_at = self._clock_ns()
        self._assignment_ns = finished_at - self._stage_started_at
        self._stage_started_at = finished_at

    def finish_result_build(self) -> None:
        finished_at = self._clock_ns()
        self._result_build_ns = finished_at - self._stage_started_at
        self._stage_started_at = finished_at

    def finish_audit(self) -> None:
        finished_at = self._clock_ns()
        self._audit_ns = finished_at - self._stage_started_at

    def start_layer(self) -> int:
        return self._clock_ns()

    def start_graph_run(self) -> int:
        self._graph_runs_count += 1
        return self._graph_runs_count

    def start_selection(self) -> int:
        return self._clock_ns()

    def finish_selection(
        self,
        *,
        started_at: int,
        candidate_routes_count: int,
        visited_nodes_count: int,
        conflict_prunes_count: int,
        bound_prunes_count: int,
    ) -> None:
        self._selection_ns += self._clock_ns() - started_at
        self._selection_runs_count += 1
        self._selection_candidate_routes_count = candidate_routes_count
        self._selection_visited_nodes_count += visited_nodes_count
        self._selection_conflict_prunes_count += conflict_prunes_count
        self._selection_bound_prunes_count += bound_prunes_count

    def record_lns_search(
        self,
        *,
        iterations_count: int,
        accepted_count: int,
        improvements_count: int,
        operator_uses: tuple[tuple[str, int], ...],
    ) -> None:
        self._lns_search = LnsSearchDiagnostics(
            iterations_count=iterations_count,
            accepted_count=accepted_count,
            improvements_count=improvements_count,
            operator_uses=operator_uses,
        )

    def add_layer(
        self,
        *,
        started_at: int,
        engineer_id: uuid.UUID,
        graph_run_id: int,
        window_start: datetime,
        window_end: datetime,
        jobs_count: int,
        input_states_count: int,
        transition_attempts_count: int,
        feasible_transitions_count: int,
        rejected_by_time_count: int,
        rejected_by_pareto_count: int,
        pruned_by_pareto_count: int,
        candidates_count: int,
        output_states_count: int,
    ) -> None:
        elapsed_ns = self._clock_ns() - started_at
        self._layers.append(
            LayerDiagnostics(
                engineer_id=engineer_id,
                graph_run_id=graph_run_id,
                window_start=window_start,
                window_end=window_end,
                jobs_count=jobs_count,
                input_states_count=input_states_count,
                transition_attempts_count=transition_attempts_count,
                feasible_transitions_count=feasible_transitions_count,
                rejected_by_time_count=rejected_by_time_count,
                rejected_by_pareto_count=rejected_by_pareto_count,
                pruned_by_pareto_count=pruned_by_pareto_count,
                candidates_count=candidates_count,
                output_states_count=output_states_count,
                elapsed_ms=self._milliseconds(elapsed_ns),
            )
        )

    def report(self) -> StrategyDiagnostics:
        total_ns = self._clock_ns() - self._total_started_at
        selection = None
        if self._selection_runs_count:
            selection = SelectionDiagnostics(
                runs_count=self._selection_runs_count,
                candidate_routes_count=self._selection_candidate_routes_count,
                visited_nodes_count=self._selection_visited_nodes_count,
                conflict_prunes_count=self._selection_conflict_prunes_count,
                bound_prunes_count=self._selection_bound_prunes_count,
                elapsed_ms=self._milliseconds(self._selection_ns),
            )
        return StrategyDiagnostics(
            assignment_ms=self._milliseconds(self._assignment_ns),
            result_build_ms=self._milliseconds(self._result_build_ns),
            audit_ms=self._milliseconds(self._audit_ns),
            total_ms=self._milliseconds(total_ns),
            route_generation_ms=self._milliseconds(self._assignment_ns - self._selection_ns),
            selection=selection,
            lns_search=self._lns_search,
            layers=tuple(self._layers),
        )

    @staticmethod
    def _milliseconds(duration_ns: int) -> float:
        return duration_ns / 1_000_000
