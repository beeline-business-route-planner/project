from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from beeline_backend.application.contracts import EngineerData, PlanningSnapshot
from beeline_backend.domain.errors import DomainError
from beeline_backend.domain.model import (
    Assignment,
    PlanCandidate,
    Unassigned,
    VisitWindow,
    calculate_visit,
)


class DeterministicPlanningAlgorithm:
    """Stable integration adapter, intentionally simple and replaceable."""

    name = "deterministic-first-fit-v1"

    async def plan(self, snapshot: PlanningSnapshot) -> PlanCandidate:
        travel = snapshot.travel_by_profile.get("driving")
        if travel is None:
            raise DomainError("missing_travel_matrix", "Driving matrix is required")
        index = {location_id: position for position, location_id in enumerate(snapshot.location_ids)}
        by_engineer: dict[UUID, list[Assignment]] = defaultdict(list)
        available_at = {engineer.id: engineer.available_from for engineer in snapshot.engineers}
        available_location = {
            engineer.id: engineer.available_location_id for engineer in snapshot.engineers
        }
        engineers = {engineer.id: engineer for engineer in snapshot.engineers}
        assigned_requests: set[UUID] = set()

        for locked in sorted(snapshot.locked_assignments, key=lambda item: (item.engineer_id, item.position)):
            request = next(item for item in snapshot.requests if item.id == locked.request_id)
            engineer = engineers[locked.engineer_id]
            from_location = available_location[engineer.id]
            cell = travel.cells[index[from_location]][index[request.location_id]]
            assignment = Assignment(
                request_id=request.id,
                engineer_id=engineer.id,
                position=len(by_engineer[engineer.id]) + 1,
                from_location_id=from_location,
                location_id=request.location_id,
                arrival_at=locked.start_at,
                start_at=locked.start_at,
                finish_at=locked.finish_at,
                travel_seconds=cell.duration_seconds or 0,
                distance_meters=cell.distance_meters or 0,
                explanation="Assignment is locked because work is en route or in progress",
            )
            by_engineer[engineer.id].append(assignment)
            available_at[engineer.id] = locked.finish_at
            available_location[engineer.id] = request.location_id
            assigned_requests.add(request.id)

        unassigned: list[Unassigned] = []
        requests = sorted(
            (item for item in snapshot.requests if item.id not in assigned_requests),
            key=lambda item: (item.priority != "urgent", item.window_start, item.external_id),
        )
        for request in requests:
            if request.status == "CANCELLED":
                unassigned.append(Unassigned(request.id, "cancelled", "Request is cancelled"))
                continue
            if request.mapping_state == "needs_mapping" or request.service_minutes is None:
                unassigned.append(
                    Unassigned(
                        request.id,
                        "needs_mapping",
                        "BK/HD combination has no confirmed work-duration mapping",
                    )
                )
                continue
            feasible: list[tuple[datetime, int, EngineerData, Assignment]] = []
            rejection_codes: set[str] = set()
            for engineer in snapshot.engineers:
                if request.required_skill and request.required_skill not in engineer.skills:
                    rejection_codes.add("missing_skill")
                    continue
                if request.required_transport and request.required_transport != engineer.transport:
                    rejection_codes.add("missing_transport")
                    continue
                from_location = available_location[engineer.id]
                cell = travel.cells[index[from_location]][index[request.location_id]]
                if cell.duration_seconds is None or cell.distance_meters is None:
                    rejection_codes.add("unreachable")
                    continue
                try:
                    timing = calculate_visit(
                        available_at[engineer.id],
                        cell.duration_seconds,
                        VisitWindow(request.window_start, request.window_end),
                        request.service_minutes,
                        engineer.shift_end,
                    )
                except DomainError as exc:
                    rejection_codes.add(exc.code)
                    continue
                candidate = Assignment(
                    request_id=request.id,
                    engineer_id=engineer.id,
                    position=len(by_engineer[engineer.id]) + 1,
                    from_location_id=from_location,
                    location_id=request.location_id,
                    arrival_at=timing.arrival,
                    start_at=timing.start,
                    finish_at=timing.finish,
                    travel_seconds=cell.duration_seconds,
                    distance_meters=cell.distance_meters,
                    explanation=(
                        "First feasible engineer in stable input order; skill, transport, window, "
                        "shift and directed travel time were checked"
                    ),
                )
                feasible.append((timing.finish, cell.distance_meters, engineer, candidate))
            if not feasible:
                reason = sorted(rejection_codes)[0] if rejection_codes else "no_available_engineer"
                unassigned.append(
                    Unassigned(request.id, reason, _reason_text(reason))
                )
                continue
            _, _, selected_engineer, selected = min(
                feasible, key=lambda item: (item[0], item[1], item[2].name)
            )
            by_engineer[selected.engineer_id].append(selected)
            available_at[selected.engineer_id] = selected.finish_at
            available_location[selected.engineer_id] = request.location_id
            assigned_requests.add(request.id)
        assignments = tuple(
            assignment
            for engineer_id in sorted(by_engineer, key=str)
            for assignment in by_engineer[engineer_id]
        )
        return PlanCandidate(
            schema_version=snapshot.schema_version,
            input_version=snapshot.input_version,
            assignments=assignments,
            unassigned=tuple(unassigned),
        )


def _reason_text(reason: str) -> str:
    return {
        "missing_skill": "No engineer with the required skill is available",
        "missing_transport": "No engineer has the required transport",
        "unreachable": "The routing provider reports no reachable path",
        "outside_client_window": "Travel and work do not fully fit in the client window",
        "outside_shift": "Travel and work do not fully fit in the engineer shift",
        "no_available_engineer": "No feasible engineer was found",
    }.get(reason, reason)


def validate_candidate(snapshot: PlanningSnapshot, candidate: PlanCandidate) -> None:
    errors: list[dict[str, object]] = []
    if candidate.schema_version != snapshot.schema_version:
        errors.append({"code": "schema_version_mismatch"})
    if candidate.input_version != snapshot.input_version:
        errors.append({"code": "input_version_mismatch"})
    request_by_id = {item.id: item for item in snapshot.requests}
    engineer_by_id = {item.id: item for item in snapshot.engineers}
    seen: set[UUID] = set()
    schedule: dict[UUID, list[Assignment]] = defaultdict(list)
    locked_request_ids = {item.request_id for item in snapshot.locked_assignments}
    for assignment in candidate.assignments:
        request = request_by_id.get(assignment.request_id)
        engineer = engineer_by_id.get(assignment.engineer_id)
        if request is None:
            errors.append({"code": "unknown_request", "request_id": str(assignment.request_id)})
            continue
        if engineer is None:
            errors.append({"code": "unknown_engineer", "engineer_id": str(assignment.engineer_id)})
            continue
        if request.id in seen:
            errors.append({"code": "duplicate_assignment", "request_id": str(request.id)})
        seen.add(request.id)
        if assignment.finish_at > request.window_end or assignment.start_at < request.window_start:
            errors.append({"code": "window_violation", "request_id": str(request.id)})
        if assignment.finish_at > engineer.shift_end or assignment.start_at < engineer.shift_start:
            errors.append({"code": "shift_violation", "request_id": str(request.id)})
        if request.required_skill and request.required_skill not in engineer.skills:
            errors.append({"code": "skill_violation", "request_id": str(request.id)})
        if request.required_transport and request.required_transport != engineer.transport:
            errors.append({"code": "transport_violation", "request_id": str(request.id)})
        if request.status == "CANCELLED":
            errors.append({"code": "cancelled_request_assigned", "request_id": str(request.id)})
        expected_service_seconds = (request.service_minutes or 0) * 60
        if int((assignment.finish_at - assignment.start_at).total_seconds()) != expected_service_seconds:
            errors.append({"code": "service_duration_mismatch", "request_id": str(request.id)})
        schedule[engineer.id].append(assignment)
    for engineer_id, items in schedule.items():
        engineer = engineer_by_id[engineer_id]
        ordered = sorted(items, key=lambda item: item.position)
        if [item.position for item in ordered] != list(range(1, len(ordered) + 1)):
            errors.append({"code": "invalid_route_positions", "engineer_id": str(engineer_id)})
        previous_finish = engineer.available_from
        previous_location = engineer.available_location_id
        matrix = snapshot.travel_by_profile.get("driving")
        location_index = {item: index for index, item in enumerate(snapshot.location_ids)}
        for assignment in ordered:
            if assignment.from_location_id != previous_location:
                errors.append(
                    {"code": "route_continuity_violation", "request_id": str(assignment.request_id)}
                )
            if assignment.request_id not in locked_request_ids and matrix is not None:
                cell = matrix.cells[location_index[previous_location]][location_index[assignment.location_id]]
                if (
                    cell.duration_seconds != assignment.travel_seconds
                    or cell.distance_meters != assignment.distance_meters
                ):
                    errors.append(
                        {"code": "travel_matrix_mismatch", "request_id": str(assignment.request_id)}
                    )
                expected_arrival = previous_finish + timedelta(seconds=assignment.travel_seconds)
                if assignment.arrival_at != expected_arrival:
                    errors.append(
                        {"code": "arrival_time_mismatch", "request_id": str(assignment.request_id)}
                    )
            previous_finish = assignment.finish_at
            previous_location = assignment.location_id
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.finish_at > current.arrival_at:
                errors.append({"code": "engineer_overlap", "engineer_id": str(engineer_id)})
    unassigned_ids = [item.request_id for item in candidate.unassigned]
    if len(unassigned_ids) != len(set(unassigned_ids)):
        errors.append({"code": "duplicate_unassigned"})
    covered = seen | set(unassigned_ids)
    expected = set(request_by_id)
    if covered != expected:
        errors.append(
            {
                "code": "request_coverage_mismatch",
                "missing": [str(item) for item in sorted(expected - covered, key=str)],
                "extra": [str(item) for item in sorted(covered - expected, key=str)],
            }
        )
    locked = {item.request_id: item for item in snapshot.locked_assignments}
    actual = {item.request_id: item for item in candidate.assignments}
    for request_id, expected_assignment in locked.items():
        result = actual.get(request_id)
        if result is None or result.engineer_id != expected_assignment.engineer_id:
            errors.append({"code": "locked_assignment_changed", "request_id": str(request_id)})
    if errors:
        raise DomainError(
            "invalid_algorithm_result",
            "Planning algorithm result failed validation",
            {"violations": errors},
        )
