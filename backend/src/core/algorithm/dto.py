import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from src.core.algorithm.enums import DistributionMode
from src.core.db.enums import Region, Skill, UnassignedReason, VehicleType


class TravelMatrix(Protocol):
    """Прогноз времени и расстояния, полученный вне алгоритма."""

    def minutes(self, from_id: uuid.UUID, to_id: uuid.UUID) -> int: ...

    def kilometers(self, from_id: uuid.UUID, to_id: uuid.UUID) -> Decimal: ...


@dataclass(frozen=True)
class RequestSnapshot:
    """Заявка в сохранённом виде до алгоритмической нормализации."""

    id: uuid.UUID
    latitude: Decimal | None
    longitude: Decimal | None
    window_start: datetime
    window_end: datetime
    service_minutes: int
    priority: int
    required_skill: Skill
    required_vehicle_type: VehicleType | None


@dataclass(frozen=True)
class EngineerSnapshot:
    """Инженер в сохранённом виде до алгоритмической нормализации."""

    id: uuid.UUID
    start_latitude: Decimal | None
    start_longitude: Decimal | None
    shift_start: datetime
    shift_end: datetime
    skills: frozenset[Skill]
    vehicle_type: VehicleType
    is_available: bool


@dataclass(frozen=True)
class InitialPlanningSnapshot:
    """Сырые данные округа и единый cutoff, зафиксированный orchestration."""

    region: Region
    planning_date: date
    calculation_cutoff_at: datetime
    mode: DistributionMode
    requests: tuple[RequestSnapshot, ...]
    engineers: tuple[EngineerSnapshot, ...]


@dataclass(frozen=True)
class RoutePoint:
    id: uuid.UUID
    latitude: Decimal
    longitude: Decimal


@dataclass(frozen=True)
class LayerMatrixRequest:
    """Матрица, которую orchestration должна получить у routing-провайдера."""

    window_start: datetime
    window_end: datetime
    traffic_reference_at: datetime
    vehicle_type: VehicleType
    source_ids: frozenset[uuid.UUID]
    target_ids: frozenset[uuid.UUID]


@dataclass(frozen=True)
class Job:
    """Нормализованная заявка с эффективным окном начала работ."""

    id: uuid.UUID
    latitude: Decimal
    longitude: Decimal
    source_window_start: datetime
    source_window_end: datetime
    release_at: datetime
    latest_start_at: datetime
    service_minutes: int
    priority: int
    required_skill: Skill
    required_vehicle_type: VehicleType | None
    is_emergency: bool = False


@dataclass(frozen=True)
class Engineer:
    """Инженер и стартовое состояние рассчитываемого маршрута."""

    id: uuid.UUID
    start_latitude: Decimal
    start_longitude: Decimal
    shift_start: datetime
    available_from: datetime
    shift_end: datetime
    skills: frozenset[Skill]
    vehicle_type: VehicleType
    is_available: bool


@dataclass(frozen=True)
class LayerTravelMatrix:
    vehicle_type: VehicleType
    travel_matrix: TravelMatrix


@dataclass(frozen=True)
class LayerMatrix:
    """Ответ routing-провайдера на один `LayerMatrixRequest`."""

    request: LayerMatrixRequest
    travel_matrix: TravelMatrix


@dataclass(frozen=True)
class InitialPlanningDraft:
    """Нормализованный snapshot, ожидающий матрицы своих слоёв."""

    region: Region
    planning_date: date
    calculation_cutoff_at: datetime
    mode: DistributionMode
    jobs: tuple[Job, ...]
    engineers: tuple[Engineer, ...]
    points: tuple[RoutePoint, ...]
    matrix_requests: tuple[LayerMatrixRequest, ...]


@dataclass(frozen=True)
class PlanningLayer:
    """Прогнозы пробок и заявки с одним эффективным окном."""

    window_start: datetime
    window_end: datetime
    traffic_reference_at: datetime
    request_ids: frozenset[uuid.UUID]
    matrices: tuple[LayerTravelMatrix, ...]


@dataclass(frozen=True)
class InitialPlanningInput:
    """Неизменяемый вход для независимого расчёта одного округа."""

    region: Region
    planning_date: date
    calculation_cutoff_at: datetime
    mode: DistributionMode
    jobs: tuple[Job, ...]
    engineers: tuple[Engineer, ...]
    layers: tuple[PlanningLayer, ...]


@dataclass(frozen=True)
class Stop:
    request_id: uuid.UUID
    sequence_number: int
    arrival: datetime
    start: datetime
    finish: datetime
    travel_minutes: int
    distance_km: Decimal


@dataclass(frozen=True)
class Route:
    engineer_id: uuid.UUID
    stops: tuple[Stop, ...]
    service_minutes: int
    travel_minutes: int
    distance_km: Decimal
    utilization_without_travel: Decimal
    utilization_with_travel: Decimal


@dataclass(frozen=True)
class UnassignedJob:
    job_id: uuid.UUID
    reason: UnassignedReason


@dataclass(frozen=True)
class PlanMetrics:
    engineers_available_count: int
    engineers_used_count: int
    assigned_requests_count: int
    unassigned_requests_count: int
    total_service_minutes: int
    total_travel_minutes: int
    total_mileage_km: Decimal
    average_utilization_without_travel: Decimal
    average_utilization_with_travel: Decimal


@dataclass(frozen=True)
class InitialPlanningResult:
    """Полный проверенный результат расчёта; это не сохраняемый Plan."""

    region: Region
    planning_date: date
    calculation_cutoff_at: datetime
    mode: DistributionMode
    routes: tuple[Route, ...]
    unassigned: tuple[UnassignedJob, ...]
    metrics: PlanMetrics
    algorithm_version: str


@dataclass(frozen=True)
class RouteCandidate:
    """Допустимая route column конкретного инженера."""

    engineer_id: uuid.UUID
    request_ids: tuple[uuid.UUID, ...]
    request_mask: int
    priority_score: int
    travel_minutes: int
    service_minutes: int


@dataclass(frozen=True, order=True)
class SelectionKey:
    priority_score: int
    assigned_count: int
    mode_score: int
    negative_travel_minutes: int
    tie_breaker: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class CandidateSelectionResult:
    routes: dict[uuid.UUID, tuple[uuid.UUID, ...]]
    quality_key: SelectionKey
    visited_nodes_count: int
    conflict_prunes_count: int
    bound_prunes_count: int


@dataclass(frozen=True)
class LayerDiagnostics:
    """Агрегаты поиска по графу для одного инженера и одного слоя."""

    engineer_id: uuid.UUID
    graph_run_id: int
    window_start: datetime
    window_end: datetime
    jobs_count: int
    input_states_count: int
    transition_attempts_count: int
    feasible_transitions_count: int
    rejected_by_time_count: int
    rejected_by_pareto_count: int
    pruned_by_pareto_count: int
    candidates_count: int
    output_states_count: int
    elapsed_ms: float


@dataclass(frozen=True)
class SelectionDiagnostics:
    """Агрегаты глобального выбора route columns."""

    runs_count: int
    candidate_routes_count: int
    visited_nodes_count: int
    conflict_prunes_count: int
    bound_prunes_count: int
    elapsed_ms: float


@dataclass(frozen=True)
class LnsSearchDiagnostics:
    """Агрегаты одного запуска LNS."""

    iterations_count: int
    accepted_count: int
    improvements_count: int
    operator_uses: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class StrategyDiagnostics:
    """Отчёт о времени и объёме поиска, создаётся только диагностическим прогоном."""

    assignment_ms: float
    result_build_ms: float
    audit_ms: float
    total_ms: float
    route_generation_ms: float
    selection: SelectionDiagnostics | None
    lns_search: LnsSearchDiagnostics | None
    layers: tuple[LayerDiagnostics, ...]


@dataclass(frozen=True)
class DiagnosedPlanningResult:
    """Проверенный результат вместе с несохраняемой диагностикой."""

    result: InitialPlanningResult
    diagnostics: StrategyDiagnostics
