import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from src.api.plans.diff_dto import PlanDiffDTO, PlanMetricsDTO
from src.api.plans.enums import RequestGroupKey
from src.core.db.enums import (
    ApprovalStatus,
    PlanKind,
    Region,
    Skill,
    UnassignedReason,
    VehicleType,
)


@dataclass(frozen=True)
class EngineerCardDTO:
    """Мини-карточка инженера — вложена в тайл заявки (см. docs/PLANS_API.md)."""

    engineer_id: uuid.UUID
    name: str


@dataclass(frozen=True)
class RequestTileDTO:
    """Один тайл заявки — что нужно на карточке плана (не полная заявка, см. `RequestDTO`).

    `sequence_number` — номер остановки в маршруте `assigned_engineer` (1 =
    первая после старта и т.д.) — нужен фронту, чтобы пронумеровать точки
    маршрута на карте; `null` у неразмещённых заявок. Тот же тайл
    используется и в плоском списке (`RequestGroupDTO`), и внутри
    `EngineerTileDTO.stops` (там `stops` уже отсортирован по этому полю, но
    само число всё равно передаётся явно, а не подразумевается по позиции в
    массиве)."""

    request_id: uuid.UUID
    external_id: int
    address: str
    district: str
    latitude: Decimal | None
    longitude: Decimal | None
    window_start: datetime
    window_end: datetime
    priority: int
    required_skill: Skill
    planned_arrival: datetime | None
    planned_start: datetime | None
    planned_finish: datetime | None
    sequence_number: int | None
    travel_minutes: int | None
    distance_km: Decimal | None
    is_locked: bool
    assigned_engineer: EngineerCardDTO | None
    unassigned_reason: UnassignedReason | None


@dataclass(frozen=True)
class RequestGroupDTO:
    """Один сворачиваемый бокс на вкладке «Заявки» — см. docs/PLANS_API.md.

    Только ключ (`group`), без текстовой подписи — подписи/иконки/цвета для
    восьми фиксированных боксов знает фронт, бэку незачем возить русский
    текст в API-ответе (ключи стабильны, порядок массива и есть порядок
    отображения)."""

    group: RequestGroupKey
    requests: tuple[RequestTileDTO, ...]


@dataclass(frozen=True)
class EngineerTileDTO:
    """Один тайл вкладки «Инженеры» — вместе со своим маршрутом (`stops`)."""

    engineer_id: uuid.UUID
    name: str
    vehicle_type: VehicleType
    shift_start: datetime
    shift_end: datetime
    start_latitude: Decimal | None
    start_longitude: Decimal | None
    assigned_requests_count: int
    route_distance_km: Decimal
    workload_without_travel: Decimal
    workload_with_travel: Decimal
    stops: tuple[RequestTileDTO, ...]


@dataclass(frozen=True)
class PlanDetailDTO:
    """Полный ответ на `GET /api/plans/current`/`GET /api/plans/{plan_id}`."""

    id: uuid.UUID
    region: Region
    planning_date: date
    kind: PlanKind
    approval_status: ApprovalStatus
    created_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    approval_deadline: datetime | None
    is_current: bool
    can_approve: bool
    can_reject: bool
    calculation_cutoff_at: datetime
    based_on_plan_id: uuid.UUID | None
    triggered_by_event_id: uuid.UUID | None
    metrics: PlanMetricsDTO
    request_groups: tuple[RequestGroupDTO, ...]
    engineers: tuple[EngineerTileDTO, ...]
    diff: PlanDiffDTO | None


@dataclass(frozen=True)
class PlanSummaryDTO:
    """Один элемент списка `GET /api/plans` — шапка плана без содержимого."""

    id: uuid.UUID
    region: Region
    planning_date: date
    kind: PlanKind
    approval_status: ApprovalStatus
    created_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    approval_deadline: datetime | None
    based_on_plan_id: uuid.UUID | None
    triggered_by_event_id: uuid.UUID | None
    is_current: bool
    assigned_requests_count: int
    unassigned_requests_count: int
    engineers_used_count: int
    total_mileage_km: Decimal
