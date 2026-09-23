import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, time
from decimal import Decimal

from src.api.plans.dto import (
    EngineerCardDTO,
    EngineerTileDTO,
    PlanDetailDTO,
    RequestGroupDTO,
    RequestTileDTO,
)
from src.api.plans.enums import RequestGroupKey
from src.core.db.enums import RequestPriority, UnassignedReason
from src.core.db.models import Engineer, Plan, PlanStop, Request
from src.core.db.models.plan_unassigned_request import PlanUnassignedRequest


class PlanPresenter:
    @staticmethod
    def build_detail(
        plan: Plan,
        requests: Sequence[Request],
        engineers: Sequence[Engineer],
        stops: Sequence[PlanStop],
        unassigned: Sequence[PlanUnassignedRequest],
        default_shift_start: time,
        default_shift_end: time,
    ) -> PlanDetailDTO:
        engineers_by_id = {engineer.id: engineer for engineer in engineers}
        stop_by_request_id = {stop.request_id: stop for stop in stops}
        reason_by_request_id = {item.request_id: item.reason for item in unassigned}

        stops_by_engineer_id: dict[uuid.UUID, list[PlanStop]] = defaultdict(list)
        for stop in stops:
            stops_by_engineer_id[stop.engineer_id].append(stop)

        tiles_by_request_id = {
            request.id: PlanPresenter._to_request_tile(
                request,
                stop_by_request_id.get(request.id),
                reason_by_request_id.get(request.id),
                engineers_by_id,
            )
            for request in requests
        }

        return PlanDetailDTO(
            id=plan.id,
            region=plan.region,
            kind=plan.kind,
            is_baseline=False,
            created_at=plan.created_at,
            based_on_plan_id=plan.based_on_plan_id,
            triggered_by_event_id=plan.triggered_by_event_id,
            total_mileage_km=plan.total_mileage_km,
            engineers_used_count=plan.engineers_used_count,
            request_groups=PlanPresenter._group_requests(
                tiles_by_request_id.values(), default_shift_start, default_shift_end
            ),
            engineers=tuple(
                sorted(
                    (
                        PlanPresenter._to_engineer_tile(
                            engineer,
                            sorted(
                                stops_by_engineer_id[engineer.id],
                                key=lambda stop: stop.sequence_number,
                            ),
                            tiles_by_request_id,
                        )
                        for engineer in engineers
                        if engineer.id in stops_by_engineer_id
                    ),
                    key=lambda tile: tile.name,
                )
            ),
        )

    @staticmethod
    def _to_request_tile(
        request: Request,
        stop: PlanStop | None,
        reason: UnassignedReason | None,
        engineers_by_id: dict[uuid.UUID, Engineer],
    ) -> RequestTileDTO:
        assigned_engineer = None
        if stop is not None:
            engineer = engineers_by_id[stop.engineer_id]
            assigned_engineer = EngineerCardDTO(engineer_id=engineer.id, name=engineer.name)
        return RequestTileDTO(
            request_id=request.id,
            address=request.address,
            district=request.district,
            latitude=request.latitude,
            longitude=request.longitude,
            window_start=request.window_start,
            window_end=request.window_end,
            priority=request.priority,
            required_skill=request.required_skill,
            planned_start=stop.planned_start if stop is not None else None,
            planned_finish=stop.planned_finish if stop is not None else None,
            sequence_number=stop.sequence_number if stop is not None else None,
            assigned_engineer=assigned_engineer,
            unassigned_reason=reason,
        )

    @staticmethod
    def _group_requests(
        tiles: Iterable[RequestTileDTO],
        default_shift_start: time,
        default_shift_end: time,
    ) -> tuple[RequestGroupDTO, ...]:
        buckets: dict[RequestGroupKey, list[RequestTileDTO]] = defaultdict(list)
        for tile in tiles:
            key = PlanPresenter._classify(tile, default_shift_start, default_shift_end)
            buckets[key].append(tile)

        return tuple(
            RequestGroupDTO(
                group=key,
                requests=tuple(
                    sorted(
                        buckets.get(key, ()),
                        key=lambda tile: (tile.planned_start or datetime.min, tile.address),
                    )
                ),
            )
            for key in RequestGroupKey
        )

    @staticmethod
    def _classify(
        tile: RequestTileDTO,
        default_shift_start: time,
        default_shift_end: time,
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

    @staticmethod
    def _to_engineer_tile(
        engineer: Engineer,
        stops: Sequence[PlanStop],
        tiles_by_request_id: dict[uuid.UUID, RequestTileDTO],
    ) -> EngineerTileDTO:
        return EngineerTileDTO(
            engineer_id=engineer.id,
            name=engineer.name,
            vehicle_type=engineer.vehicle_type,
            shift_start=engineer.shift_start,
            shift_end=engineer.shift_end,
            start_latitude=engineer.start_point_latitude,
            start_longitude=engineer.start_point_longitude,
            assigned_requests_count=len(stops),
            route_distance_km=sum((stop.distance_km for stop in stops), start=Decimal("0")),
            stops=tuple(tiles_by_request_id[stop.request_id] for stop in stops),
        )
