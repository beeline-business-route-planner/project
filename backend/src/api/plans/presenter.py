import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, time

from src.api.plans.diff_dto import (
    PlanDiffDTO,
    PlanSnapshotDTO,
    SnapshotEngineerDTO,
    SnapshotRequestDTO,
)
from src.api.plans.dto import (
    EngineerCardDTO,
    EngineerTileDTO,
    PlanDetailDTO,
    RequestGroupDTO,
    RequestTileDTO,
)
from src.api.plans.enums import RequestGroupKey
from src.core.db.enums import ApprovalStatus, RequestPriority


class PlanPresenter:
    """Формирует публичную карточку исключительно из полного snapshot."""

    @staticmethod
    def build_detail(
        snapshot: PlanSnapshotDTO,
        is_current: bool,
        approval_deadline: datetime | None,
        diff: PlanDiffDTO | None,
        default_shift_start: time,
        default_shift_end: time,
    ) -> PlanDetailDTO:
        engineers_by_id = {item.engineer_id: item for item in snapshot.engineers}
        tiles = tuple(
            PlanPresenter._to_request_tile(item, engineers_by_id) for item in snapshot.requests
        )
        tiles_by_id = {item.request_id: item for item in tiles}
        actionable = snapshot.approval_status == ApprovalStatus.PENDING
        return PlanDetailDTO(
            id=snapshot.id,
            region=snapshot.region,
            planning_date=snapshot.planning_date,
            kind=snapshot.kind,
            approval_status=snapshot.approval_status,
            created_at=snapshot.created_at,
            approved_at=snapshot.approved_at,
            rejected_at=snapshot.rejected_at,
            approval_deadline=approval_deadline,
            is_current=is_current,
            can_approve=actionable,
            can_reject=actionable,
            calculation_cutoff_at=snapshot.calculation_cutoff_at,
            based_on_plan_id=snapshot.based_on_plan_id,
            triggered_by_event_id=snapshot.triggered_by_event_id,
            metrics=snapshot.metrics,
            request_groups=PlanPresenter._group_requests(
                tiles, default_shift_start, default_shift_end
            ),
            engineers=tuple(
                EngineerTileDTO(
                    engineer_id=engineer.engineer_id,
                    name=engineer.name,
                    vehicle_type=engineer.vehicle_type,
                    shift_start=engineer.shift_start,
                    shift_end=engineer.shift_end,
                    start_latitude=engineer.start_latitude,
                    start_longitude=engineer.start_longitude,
                    assigned_requests_count=len(engineer.requests),
                    route_distance_km=engineer.route_distance_km,
                    workload_without_travel=engineer.workload_without_travel,
                    workload_with_travel=engineer.workload_with_travel,
                    stops=tuple(tiles_by_id[item.request_id] for item in engineer.requests),
                )
                for engineer in sorted(snapshot.engineers, key=lambda item: item.name)
                if engineer.requests
            ),
            diff=diff,
        )

    @staticmethod
    def _to_request_tile(
        request: SnapshotRequestDTO, engineers_by_id: dict[uuid.UUID, SnapshotEngineerDTO]
    ) -> RequestTileDTO:
        engineer = engineers_by_id.get(request.engineer_id) if request.engineer_id else None
        assigned_engineer = None
        if engineer is not None:
            assigned_engineer = EngineerCardDTO(
                engineer_id=engineer.engineer_id, name=engineer.name
            )
        return RequestTileDTO(
            request_id=request.request_id,
            external_id=request.external_id,
            address=request.address,
            district=request.district,
            latitude=request.latitude,
            longitude=request.longitude,
            window_start=request.window_start,
            window_end=request.window_end,
            priority=request.priority,
            required_skill=request.required_skill,
            planned_arrival=request.planned_arrival,
            planned_start=request.planned_start,
            planned_finish=request.planned_finish,
            sequence_number=request.sequence_number,
            travel_minutes=request.travel_minutes,
            distance_km=request.distance_km,
            is_locked=request.is_locked,
            assigned_engineer=assigned_engineer,
            unassigned_reason=request.unassigned_reason,
        )

    @staticmethod
    def _group_requests(
        tiles: Iterable[RequestTileDTO],
        default_shift_start: time,
        default_shift_end: time,
    ) -> tuple[RequestGroupDTO, ...]:
        buckets: dict[RequestGroupKey, list[RequestTileDTO]] = defaultdict(list)
        for tile in tiles:
            buckets[PlanPresenter._classify(tile, default_shift_start, default_shift_end)].append(
                tile
            )
        return tuple(
            RequestGroupDTO(
                group=key,
                requests=tuple(
                    sorted(
                        buckets.get(key, ()),
                        key=lambda item: (item.planned_start or datetime.min, item.address),
                    )
                ),
            )
            for key in RequestGroupKey
        )

    @staticmethod
    def _classify(
        tile: RequestTileDTO, default_shift_start: time, default_shift_end: time
    ) -> RequestGroupKey:
        if tile.planned_start is None:
            return RequestGroupKey.UNASSIGNED
        if tile.priority == RequestPriority.EMERGENCY:
            return RequestGroupKey.EMERGENCY
        earliest_bucket_start = default_shift_start.hour
        latest_bucket_start = default_shift_end.hour - 2
        bucket_start = tile.planned_start.hour - tile.planned_start.hour % 2
        bucket_start = max(earliest_bucket_start, min(latest_bucket_start, bucket_start))
        return RequestGroupKey(f"{bucket_start}-{bucket_start + 2}")
