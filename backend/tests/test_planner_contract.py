from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from beeline_backend.application.contracts import (
    EngineerData,
    LocationData,
    PlanningSnapshot,
    RequestData,
    TravelCell,
    TravelSnapshot,
)
from beeline_backend.application.planner import DeterministicPlanningAlgorithm, validate_candidate
from beeline_backend.domain.errors import DomainError
from beeline_backend.domain.model import Priority, RequestStatus


@pytest.mark.asyncio
async def test_planner_uses_routing_time_once_and_validator_rejects_mismatch() -> None:
    timezone = ZoneInfo("Europe/Moscow")
    office_id = uuid4()
    request_location_id = uuid4()
    request_id = uuid4()
    engineer_id = uuid4()
    start = datetime(2026, 8, 17, 8, tzinfo=timezone)
    snapshot = PlanningSnapshot(
        input_version="input-v1",
        dataset_id=uuid4(),
        base_plan_id=None,
        scenario_id=uuid4(),
        planning_date=date(2026, 8, 17),
        timezone="Europe/Moscow",
        as_of=start,
        locations=[
            LocationData(id=office_id, address="Office", latitude=55.7, longitude=37.6),
            LocationData(
                id=request_location_id, address="Client", latitude=55.8, longitude=37.7
            ),
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
                status=RequestStatus.NOT_SENT,
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
        locked_assignments=[],
        execution_snapshot={},
        events=[],
        policies={},
    )
    candidate = await DeterministicPlanningAlgorithm().plan(snapshot)
    validate_candidate(snapshot, candidate)
    assignment = candidate.assignments[0]
    assert assignment.travel_seconds == 600
    assert int((assignment.finish_at - assignment.start_at).total_seconds() / 60) == 70

    damaged = candidate.__class__(
        schema_version=candidate.schema_version,
        input_version=candidate.input_version,
        assignments=(replace(assignment, travel_seconds=1800),),
        unassigned=candidate.unassigned,
    )
    with pytest.raises(DomainError) as exc_info:
        validate_candidate(snapshot, damaged)
    assert exc_info.value.code == "invalid_algorithm_result"
    assert any(
        item["code"] == "travel_matrix_mismatch"
        for item in exc_info.value.details["violations"]
    )

