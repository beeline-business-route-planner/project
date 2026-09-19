from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from beeline_backend.application.contracts import (
    EngineerData,
    LocationData,
    LockedAssignmentData,
    PlanningSnapshot,
    RequestData,
    TravelCell,
    TravelSnapshot,
)
from beeline_backend.application.planner import DeterministicPlanningAlgorithm, validate_candidate
from beeline_backend.domain.errors import DomainError
from beeline_backend.domain.model import PlanCandidate, Priority, RequestStatus, Unassigned


def _snapshot(*, locked: bool = False) -> PlanningSnapshot:
    timezone = ZoneInfo("Europe/Moscow")
    office_id = uuid4()
    request_location_id = uuid4()
    request_id = uuid4()
    engineer_id = uuid4()
    start = datetime(2026, 8, 17, 8, tzinfo=timezone)
    return PlanningSnapshot(
        input_version="input-v1",
        dataset_id=uuid4(),
        base_plan_id=uuid4() if locked else None,
        scenario_id=uuid4(),
        planning_date=date(2026, 8, 17),
        timezone="Europe/Moscow",
        as_of=start,
        locations=[
            LocationData(id=office_id, address="Office", latitude=55.7, longitude=37.6),
            LocationData(id=request_location_id, address="Client", latitude=55.8, longitude=37.7),
        ],
        location_ids=[office_id, request_location_id],
        travel_by_profile={
            "driving": TravelSnapshot(
                provider="test",
                provider_version="1",
                captured_at=start,
                profile="driving",
                cells=[
                    [
                        TravelCell(duration_seconds=0, distance_meters=0),
                        TravelCell(duration_seconds=600, distance_meters=1000),
                    ],
                    [
                        TravelCell(duration_seconds=900, distance_meters=1200),
                        TravelCell(duration_seconds=0, distance_meters=0),
                    ],
                ],
            )
        },
        requests=[
            RequestData(
                id=request_id,
                external_id="1",
                location_id=request_location_id,
                window_start=start,
                window_end=datetime(2026, 8, 17, 12, tzinfo=timezone),
                service_minutes=70,
                full_normative_minutes=90,
                required_skill="connection",
                required_transport=None,
                priority=Priority.NORMAL,
                status=RequestStatus.IN_PROGRESS if locked else RequestStatus.NOT_SENT,
            )
        ],
        engineers=[
            EngineerData(
                id=engineer_id,
                name="Engineer",
                office_location_id=office_id,
                shift_start=start,
                shift_end=datetime(2026, 8, 17, 18, tzinfo=timezone),
                skills={"connection"},
                transport="car",
                available_from=start,
                available_location_id=office_id,
            )
        ],
        locked_assignments=[
            LockedAssignmentData(
                request_id=request_id,
                engineer_id=engineer_id,
                position=1,
                location_id=request_location_id,
                start_at=start + timedelta(minutes=10),
                finish_at=start + timedelta(minutes=80),
            )
        ]
        if locked
        else [],
        execution_snapshot={},
        events=[],
        policies={},
    )


def _violation_codes(snapshot: PlanningSnapshot, candidate: PlanCandidate) -> set[str]:
    with pytest.raises(DomainError) as exc_info:
        validate_candidate(snapshot, candidate)
    assert exc_info.value.code == "invalid_algorithm_result"
    violations = cast(list[dict[str, object]], exc_info.value.details["violations"])
    return {str(item["code"]) for item in violations}


@pytest.mark.asyncio
async def test_planner_uses_routing_time_once_and_validator_rejects_mismatch() -> None:
    snapshot = _snapshot()
    candidate = await DeterministicPlanningAlgorithm().plan(snapshot)
    validate_candidate(snapshot, candidate)
    assignment = candidate.assignments[0]
    assert assignment.travel_seconds == 600
    assert int((assignment.finish_at - assignment.start_at).total_seconds() / 60) == 70

    damaged = replace(candidate, assignments=(replace(assignment, travel_seconds=1800),))
    assert "travel_matrix_mismatch" in _violation_codes(snapshot, damaged)


@pytest.mark.asyncio
async def test_validator_rejects_inconsistent_assignment_contract() -> None:
    snapshot = _snapshot()
    candidate = await DeterministicPlanningAlgorithm().plan(snapshot)
    assignment = candidate.assignments[0]

    wrong_location = replace(
        candidate,
        assignments=(replace(assignment, location_id=snapshot.engineers[0].office_location_id),),
    )
    assert "request_location_mismatch" in _violation_codes(snapshot, wrong_location)

    early_start = replace(
        candidate,
        assignments=(
            replace(
                assignment,
                start_at=assignment.arrival_at - timedelta(minutes=1),
                finish_at=assignment.finish_at - timedelta(minutes=1),
            ),
        ),
    )
    assert "start_before_arrival" in _violation_codes(snapshot, early_start)

    duplicated = replace(
        candidate,
        unassigned=(Unassigned(assignment.request_id, "unexpected", "unexpected"),),
    )
    assert "assigned_and_unassigned" in _violation_codes(snapshot, duplicated)


@pytest.mark.asyncio
async def test_validator_rejects_missing_or_invalid_matrix() -> None:
    snapshot = _snapshot()
    candidate = await DeterministicPlanningAlgorithm().plan(snapshot)
    without_matrix = snapshot.model_copy(update={"travel_by_profile": {}})
    assert "missing_travel_matrix" in _violation_codes(without_matrix, candidate)

    travel = snapshot.travel_by_profile["driving"]
    invalid_matrix = snapshot.model_copy(
        update={
            "travel_by_profile": {
                "driving": travel.model_copy(
                    update={"cells": [[TravelCell(duration_seconds=0, distance_meters=0)]]}
                )
            }
        }
    )
    assert "invalid_travel_matrix_shape" in _violation_codes(invalid_matrix, candidate)


@pytest.mark.asyncio
async def test_validator_rejects_changed_lock() -> None:
    snapshot = _snapshot(locked=True)
    candidate = await DeterministicPlanningAlgorithm().plan(snapshot)
    validate_candidate(snapshot, candidate)
    assignment = candidate.assignments[0]
    shifted = replace(
        assignment,
        arrival_at=assignment.arrival_at + timedelta(minutes=5),
        start_at=assignment.start_at + timedelta(minutes=5),
        finish_at=assignment.finish_at + timedelta(minutes=5),
    )
    assert "locked_assignment_changed" in _violation_codes(
        snapshot, replace(candidate, assignments=(shifted,))
    )
