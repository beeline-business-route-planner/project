import uuid
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from src.api.plans.diff_dto import (
    PlanMetricsDTO,
    PlanSnapshotDTO,
    SnapshotEngineerDTO,
    SnapshotRequestDTO,
)
from src.core.db.enums import UnassignedReason
from src.core.db.models import (
    Engineer,
    Plan,
    PlanEngineerState,
    PlanStop,
    PlanUnassignedRequest,
    Request,
)


class PlanSnapshotAssembler:
    """Преобразует загруженные ORM-сущности в полный immutable-снимок плана."""

    @staticmethod
    def build(
        plan: Plan,
        requests: Sequence[Request],
        engineers: Sequence[Engineer],
        engineer_states: Sequence[PlanEngineerState],
        stops: Sequence[PlanStop],
        unassigned: Sequence[PlanUnassignedRequest],
    ) -> PlanSnapshotDTO:
        engineers_by_id = {engineer.id: engineer for engineer in engineers}
        availability_by_engineer_id = {
            state.engineer_id: state.is_available for state in engineer_states
        }
        requests_by_id = {request.id: request for request in requests}
        stops_by_request_id = {stop.request_id: stop for stop in stops}
        reasons_by_request_id = {item.request_id: item.reason for item in unassigned}

        if set(stops_by_request_id) & set(reasons_by_request_id):
            raise ValueError("A request cannot be both assigned and unassigned")
        if set(requests_by_id) != set(stops_by_request_id) | set(reasons_by_request_id):
            raise ValueError("Every plan request must be assigned or unassigned")
        if set(engineers_by_id) != set(availability_by_engineer_id):
            raise ValueError("Every plan engineer must have frozen availability")

        snapshot_requests = tuple(
            PlanSnapshotAssembler._request(
                request,
                stops_by_request_id.get(request.id),
                reasons_by_request_id.get(request.id),
            )
            for request in sorted(requests, key=lambda item: str(item.id))
        )
        requests_by_engineer: dict[uuid.UUID, list[SnapshotRequestDTO]] = defaultdict(list)
        for request in snapshot_requests:
            if request.engineer_id is not None:
                if request.engineer_id not in engineers_by_id:
                    raise ValueError("Plan stop references an unknown engineer")
                requests_by_engineer[request.engineer_id].append(request)

        snapshot_engineers = tuple(
            PlanSnapshotAssembler._engineer(
                engineer,
                availability_by_engineer_id[engineer.id],
                tuple(
                    sorted(
                        requests_by_engineer.get(engineer.id, ()),
                        key=lambda item: item.sequence_number or 0,
                    )
                ),
            )
            for engineer in sorted(engineers, key=lambda item: str(item.id))
        )
        metrics = PlanSnapshotAssembler._metrics(snapshot_requests, snapshot_engineers)
        return PlanSnapshotDTO(
            id=plan.id,
            region=plan.region,
            planning_date=plan.planning_date,
            kind=plan.kind,
            approval_status=plan.approval_status,
            created_at=plan.created_at,
            approved_at=plan.approved_at,
            rejected_at=plan.rejected_at,
            calculation_cutoff_at=plan.calculation_cutoff_at,
            based_on_plan_id=plan.based_on_plan_id,
            triggered_by_event_id=plan.triggered_by_event_id,
            edited_from_plan_id=plan.edited_from_plan_id,
            metrics=metrics,
            requests=snapshot_requests,
            engineers=snapshot_engineers,
        )

    @staticmethod
    def _request(
        request: Request,
        stop: PlanStop | None,
        reason: UnassignedReason | None,
    ) -> SnapshotRequestDTO:
        return SnapshotRequestDTO(
            request_id=request.id,
            external_id=request.external_id,
            address=request.address,
            district=request.district,
            latitude=request.latitude,
            longitude=request.longitude,
            window_start=request.window_start,
            window_end=request.window_end,
            priority=request.priority,
            required_skill=request.required_skill,
            service_minutes=request.norm_minutes_without_travel,
            engineer_id=stop.engineer_id if stop is not None else None,
            sequence_number=stop.sequence_number if stop is not None else None,
            planned_arrival=stop.planned_arrival if stop is not None else None,
            planned_start=stop.planned_start if stop is not None else None,
            planned_finish=stop.planned_finish if stop is not None else None,
            travel_minutes=stop.travel_minutes if stop is not None else None,
            distance_km=stop.distance_km if stop is not None else None,
            is_locked=stop.is_locked if stop is not None else False,
            unassigned_reason=reason,
            upload_id=request.upload_id,
            type_bk=request.type_bk,
            type_hd=request.type_hd,
            connection_type=request.connection_type,
            is_gigabit=request.is_gigabit,
            norm_minutes=request.norm_minutes,
        )

    @staticmethod
    def _engineer(
        engineer: Engineer,
        is_available: bool,
        requests: tuple[SnapshotRequestDTO, ...],
    ) -> SnapshotEngineerDTO:
        work_minutes = sum(item.service_minutes for item in requests)
        travel_minutes = sum(item.travel_minutes or 0 for item in requests)
        shift_minutes = int((engineer.shift_end - engineer.shift_start).total_seconds() // 60)
        return SnapshotEngineerDTO(
            engineer_id=engineer.id,
            name=engineer.name,
            vehicle_type=engineer.vehicle_type,
            shift_start=engineer.shift_start,
            shift_end=engineer.shift_end,
            start_latitude=engineer.start_point_latitude,
            start_longitude=engineer.start_point_longitude,
            is_available=is_available,
            route_distance_km=sum(
                (item.distance_km or Decimal("0") for item in requests), Decimal("0")
            ),
            workload_without_travel=PlanSnapshotAssembler._workload(work_minutes, shift_minutes),
            workload_with_travel=PlanSnapshotAssembler._workload(
                work_minutes + travel_minutes, shift_minutes
            ),
            requests=requests,
        )

    @staticmethod
    def _metrics(
        requests: tuple[SnapshotRequestDTO, ...],
        engineers: tuple[SnapshotEngineerDTO, ...],
    ) -> PlanMetricsDTO:
        assigned = tuple(item for item in requests if item.engineer_id is not None)
        available = tuple(item for item in engineers if item.is_available)
        used = tuple(item for item in engineers if item.requests)
        available_workloads = tuple(item.workload_with_travel for item in available)
        return PlanMetricsDTO(
            assigned_requests_count=len(assigned),
            unassigned_requests_count=len(requests) - len(assigned),
            engineers_used_count=len(used),
            available_engineers_count=len(available),
            total_mileage_km=sum(
                (item.distance_km or Decimal("0") for item in assigned), Decimal("0")
            ),
            total_work_minutes=sum(item.service_minutes for item in assigned),
            total_travel_minutes=sum(item.travel_minutes or 0 for item in assigned),
            average_workload_without_travel=PlanSnapshotAssembler._average(
                tuple(item.workload_without_travel for item in available)
            ),
            average_workload_with_travel=PlanSnapshotAssembler._average(available_workloads),
            average_used_workload_without_travel=PlanSnapshotAssembler._average(
                tuple(item.workload_without_travel for item in used)
            ),
            average_used_workload_with_travel=PlanSnapshotAssembler._average(
                tuple(item.workload_with_travel for item in used)
            ),
            min_workload_with_travel=min(available_workloads, default=Decimal("0")),
            max_workload_with_travel=max(available_workloads, default=Decimal("0")),
        )

    @staticmethod
    def _workload(minutes: int, shift_minutes: int) -> Decimal:
        if shift_minutes <= 0:
            return Decimal("0")
        return (Decimal(minutes) * Decimal("100") / Decimal(shift_minutes)).quantize(
            Decimal("0.01")
        )

    @staticmethod
    def _average(values: tuple[Decimal, ...]) -> Decimal:
        if not values:
            return Decimal("0")
        return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(Decimal("0.01"))
