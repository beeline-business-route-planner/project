from dataclasses import replace
from decimal import Decimal

from src.api.plans.diff_dto import (
    DecimalMetricDeltaDTO,
    EngineerDiffDTO,
    IntMetricDeltaDTO,
    PlanDiffDTO,
    PlanSnapshotDTO,
    PlanSummaryDiffDTO,
    RequestDiffDTO,
    SnapshotEngineerDTO,
    SnapshotRequestDTO,
)
from src.api.plans.enums import EngineerChange, RequestChange


class PlanDiffEngine:
    """Детерминированно сравнивает два полных immutable-снимка без I/O."""

    @staticmethod
    def compare(before: PlanSnapshotDTO, after: PlanSnapshotDTO) -> PlanDiffDTO:
        request_diffs = PlanDiffEngine._request_diffs(before.requests, after.requests)
        return PlanDiffDTO(
            base_plan_id=before.id,
            candidate_plan_id=after.id,
            summary=PlanDiffEngine._summary(before, after),
            engineers=PlanDiffEngine._engineer_diffs(
                before.engineers, after.engineers, request_diffs
            ),
            requests=request_diffs,
        )

    @staticmethod
    def _request_diffs(
        before: tuple[SnapshotRequestDTO, ...], after: tuple[SnapshotRequestDTO, ...]
    ) -> tuple[RequestDiffDTO, ...]:
        before_by_id = {item.request_id: item for item in before}
        after_by_id = {item.request_id: item for item in after}
        return tuple(
            PlanDiffEngine._request_diff(before_by_id.get(request_id), after_by_id.get(request_id))
            for request_id in sorted(before_by_id.keys() | after_by_id.keys(), key=str)
        )

    @staticmethod
    def _request_diff(
        before: SnapshotRequestDTO | None, after: SnapshotRequestDTO | None
    ) -> RequestDiffDTO:
        if before is None:
            if after is None:
                raise ValueError("At least one request snapshot is required")
            return RequestDiffDTO(after.request_id, (RequestChange.ADDED,), None, after)
        if after is None:
            return RequestDiffDTO(before.request_id, (RequestChange.REMOVED,), before, None)

        changes: list[RequestChange] = []
        if (before.engineer_id is None) != (after.engineer_id is None):
            changes.append(RequestChange.ASSIGNMENT_CHANGED)
        if (
            before.engineer_id is not None
            and after.engineer_id is not None
            and before.engineer_id != after.engineer_id
        ):
            changes.append(RequestChange.REASSIGNED)
        if before.sequence_number != after.sequence_number:
            changes.append(RequestChange.REORDERED)
        if (
            before.planned_arrival,
            before.planned_start,
            before.planned_finish,
        ) != (
            after.planned_arrival,
            after.planned_start,
            after.planned_finish,
        ):
            changes.append(RequestChange.RESCHEDULED)
        if (before.travel_minutes, before.distance_km) != (
            after.travel_minutes,
            after.distance_km,
        ):
            changes.append(RequestChange.TRAVEL_CHANGED)
        if before.unassigned_reason != after.unassigned_reason:
            changes.append(RequestChange.UNASSIGNED_REASON_CHANGED)
        if not changes:
            changes.append(RequestChange.UNCHANGED)
        return RequestDiffDTO(before.request_id, tuple(changes), before, after)

    @staticmethod
    def _engineer_diffs(
        before: tuple[SnapshotEngineerDTO, ...],
        after: tuple[SnapshotEngineerDTO, ...],
        requests: tuple[RequestDiffDTO, ...],
    ) -> tuple[EngineerDiffDTO, ...]:
        before_by_id = {
            item.engineer_id: PlanDiffEngine._canonical_engineer(item) for item in before
        }
        after_by_id = {item.engineer_id: PlanDiffEngine._canonical_engineer(item) for item in after}
        result = []
        for engineer_id in sorted(before_by_id.keys() | after_by_id.keys(), key=str):
            old = before_by_id.get(engineer_id)
            new = after_by_id.get(engineer_id)
            related = tuple(
                item
                for item in requests
                if (item.before is not None and item.before.engineer_id == engineer_id)
                or (item.after is not None and item.after.engineer_id == engineer_id)
            )
            if old is None:
                change = EngineerChange.ADDED
            elif new is None:
                change = EngineerChange.REMOVED
            elif old == new and all(item.changes == (RequestChange.UNCHANGED,) for item in related):
                change = EngineerChange.UNCHANGED
            else:
                change = EngineerChange.CHANGED
            result.append(EngineerDiffDTO(engineer_id, change, old, new, related))
        return tuple(result)

    @staticmethod
    def _canonical_engineer(engineer: SnapshotEngineerDTO) -> SnapshotEngineerDTO:
        return replace(
            engineer,
            requests=tuple(sorted(engineer.requests, key=lambda item: str(item.request_id))),
        )

    @staticmethod
    def _summary(before: PlanSnapshotDTO, after: PlanSnapshotDTO) -> PlanSummaryDiffDTO:
        old = before.metrics
        new = after.metrics
        return PlanSummaryDiffDTO(
            assigned_requests=PlanDiffEngine._int_delta(
                old.assigned_requests_count, new.assigned_requests_count
            ),
            unassigned_requests=PlanDiffEngine._int_delta(
                old.unassigned_requests_count, new.unassigned_requests_count
            ),
            engineers_used=PlanDiffEngine._int_delta(
                old.engineers_used_count, new.engineers_used_count
            ),
            total_work_minutes=PlanDiffEngine._int_delta(
                old.total_work_minutes, new.total_work_minutes
            ),
            total_travel_minutes=PlanDiffEngine._int_delta(
                old.total_travel_minutes, new.total_travel_minutes
            ),
            total_mileage_km=PlanDiffEngine._decimal_delta(
                old.total_mileage_km, new.total_mileage_km
            ),
            average_workload_without_travel=PlanDiffEngine._decimal_delta(
                old.average_workload_without_travel,
                new.average_workload_without_travel,
            ),
            average_workload_with_travel=PlanDiffEngine._decimal_delta(
                old.average_workload_with_travel, new.average_workload_with_travel
            ),
        )

    @staticmethod
    def _int_delta(before: int, after: int) -> IntMetricDeltaDTO:
        return IntMetricDeltaDTO(before, after, after - before)

    @staticmethod
    def _decimal_delta(before: Decimal, after: Decimal) -> DecimalMetricDeltaDTO:
        return DecimalMetricDeltaDTO(before, after, after - before)
