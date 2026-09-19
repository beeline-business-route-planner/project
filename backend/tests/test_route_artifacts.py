from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from beeline_backend.application.contracts import (
    EngineerData,
    LocationData,
    PlanningSnapshot,
    TravelCell,
    TravelSnapshot,
)
from beeline_backend.application.routing import (
    LineString,
    RouteBuilder,
    canonical_point,
    point_segment_distance,
    segment_key,
    simplify,
)
from beeline_backend.domain.errors import ConflictError, DomainError
from beeline_backend.domain.model import Assignment, PlanCandidate


class MemoryStore:
    def __init__(self):
        self.values = {}

    async def get_many(self, keys):
        return {key: self.values[key] for key in keys if key in self.values}

    async def put(self, segment):
        self.values.setdefault(segment.key, segment)


class CountingRouter:
    name = "osrm"
    graph_fingerprint = "graph-1"

    def __init__(self):
        self.calls = []
        self.active = 0
        self.peak = 0

    async def matrix(self, *args):
        raise AssertionError("Segment builder must not rebuild the matrix")

    async def route_geometry(self, coordinates, profile):
        self.calls.append(coordinates)
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.001)
        self.active -= 1
        a, b = coordinates
        points = [
            [
                a[1] + (b[1] - a[1]) * i / 20,
                a[0] + (b[0] - a[0]) * i / 20 + math.sin(i * math.pi / 20) * 0.00003,
            ]
            for i in range(21)
        ]
        points[0], points[-1] = [a[1], a[0]], [b[1], b[0]]
        return {
            "type": "LineString",
            "coordinates": points,
            "distance_meters": 1000,
            "duration_seconds": 120,
            "provider": "osrm",
        }


def route_fixture(count=5):
    start = datetime(2026, 8, 17, 8, tzinfo=UTC)
    locations = [
        LocationData(
            id=uuid4(), address=f"Point {i}", latitude=55.7 + i * 0.001, longitude=37.6 + i * 0.001
        )
        for i in range(count)
    ]
    engineers = [
        EngineerData(
            id=uuid4(),
            name=f"Engineer {i}",
            office_location_id=locations[0].id,
            shift_start=start,
            shift_end=start + timedelta(hours=12),
            skills={"local"},
            transport="car",
            available_from=start,
            available_location_id=locations[0].id,
        )
        for i in range(2)
    ]
    snapshot = PlanningSnapshot(
        input_version="input-1",
        dataset_id=uuid4(),
        base_plan_id=None,
        scenario_id=uuid4(),
        planning_date=date(2026, 8, 17),
        timezone="Europe/Moscow",
        as_of=start,
        locations=locations,
        location_ids=[item.id for item in locations],
        engineers=engineers,
        requests=[],
        locked_assignments=[],
        execution_snapshot={},
        events=[],
        policies={},
        travel_by_profile={
            "driving": TravelSnapshot(
                provider="osrm",
                provider_version="graph-1",
                captured_at=start,
                profile="driving",
                cells=[
                    [TravelCell(duration_seconds=120, distance_meters=1000) for _ in locations]
                    for _ in locations
                ],
            )
        },
    )

    def candidate(order):
        assignments = tuple(
            Assignment(
                request_id=uuid4(),
                engineer_id=engineers[0].id,
                position=i,
                from_location_id=locations[a].id,
                location_id=locations[b].id,
                arrival_at=start,
                start_at=start,
                finish_at=start + timedelta(minutes=5),
                travel_seconds=120,
                distance_meters=1000,
                explanation="test",
            )
            for i, (a, b) in enumerate(zip(order, order[1:], strict=False), 1)
        )
        return PlanCandidate(
            schema_version=snapshot.schema_version,
            input_version=snapshot.input_version,
            assignments=assignments,
            unassigned=(),
        )

    return snapshot, candidate


def test_segment_signature_is_directed_and_includes_graph_and_options():
    a, b = canonical_point(55.71234567, 37.61234567), (37.7, 55.8)
    base = segment_key("osrm", "graph-1", "driving", a, b, {"a": 1, "b": 2})
    assert a == (37.612346, 55.712346)
    assert base == segment_key("osrm", "graph-1", "driving", a, b, {"b": 2, "a": 1})
    for args in [
        ("osrm", "graph-1", "driving", b, a, {"a": 1, "b": 2}),
        ("osrm", "graph-2", "driving", a, b, {"a": 1, "b": 2}),
        ("osrm", "graph-1", "walking", a, b, {"a": 1, "b": 2}),
        ("2gis", "graph-1", "driving", a, b, {"a": 1, "b": 2}),
        ("osrm", "graph-1", "driving", a, b, {"a": 3, "b": 2}),
    ]:
        assert base != segment_key(*args)


def test_simplification_uses_ground_metres_and_preserves_endpoints():
    points = [(37.6 + i * 0.0001, 55.75 + math.sin(i / 12) * 0.0005) for i in range(300)]
    reduced = simplify(points, 20)
    assert reduced[0] == points[0] and reduced[-1] == points[-1]
    assert 2 < len(reduced) < len(points)
    for start, end in zip(reduced, reduced[1:], strict=False):
        for point in points[points.index(start) : points.index(end) + 1]:
            assert point_segment_distance(point, start, end) <= 20.00001
    assert 60 < point_segment_distance((37.601, 55.75), (37.6, 55.75), (37.6, 55.75)) < 64


def test_short_and_long_degenerate_lines_are_safe():
    assert simplify([(37.6, 55.7), (37.6, 55.7)], 20) == [(37.6, 55.7)] * 2
    points = [(37.6 + i / 1000000, 55.7) for i in range(10000)]
    assert len(simplify(points, 20)) == 2
    with pytest.raises(ValidationError):
        LineString(coordinates=[(37.6, 55.7)])
    with pytest.raises(ValidationError):
        LineString(coordinates=[(math.nan, 55.7), (37.6, 55.7)])


@pytest.mark.asyncio
async def test_insert_reuses_two_edges_and_builds_only_two_new_edges():
    snapshot, candidate = route_fixture()
    store, router = MemoryStore(), CountingRouter()
    builder = RouteBuilder(router, store, 20, concurrency=2)
    initial = await builder.build(snapshot, candidate([0, 1, 2, 3]))
    assert initial.segments_calculated == 3
    initial_detail = initial.routes[snapshot.engineers[0].id].detailed.model_dump()
    updated = await builder.build(snapshot, candidate([0, 1, 4, 2, 3]))
    assert (updated.segments_reused, updated.segments_calculated) == (2, 2)
    assert len(router.calls) == 5 and router.peak <= 2
    assert initial.routes[snapshot.engineers[0].id].detailed.model_dump() == initial_detail
    route = updated.routes[snapshot.engineers[0].id]
    assert len(route.detailed.stops) == 5
    assert len(route.overview.geometry.coordinates) < len(route.detailed.geometry.coordinates)
    assert updated.routes[snapshot.engineers[1].id].detailed.route_status == "empty"
    again = await builder.build(snapshot, candidate([0, 1, 4, 2, 3]))
    assert (again.segments_reused, again.segments_calculated) == (4, 0)


@pytest.mark.asyncio
async def test_concurrent_builds_deduplicate_and_graph_changes_do_not_reuse():
    snapshot, candidate = route_fixture()
    store, router = MemoryStore(), CountingRouter()
    builder = RouteBuilder(router, store, 20, concurrency=2)
    await asyncio.gather(*(builder.build(snapshot, candidate([0, 1, 2, 3])) for _ in range(2)))
    assert len(router.calls) == 3
    router.graph_fingerprint = "graph-2"
    with pytest.raises(ConflictError):
        await builder.build(snapshot, candidate([0, 1, 2, 3]))
    snapshot.travel_by_profile["driving"].provider_version = "graph-2"
    result = await builder.build(snapshot, candidate([0, 1, 2, 3]))
    assert result.segments_calculated == 3


@pytest.mark.asyncio
async def test_discontinuous_snapping_is_not_joined_with_a_fake_line():
    snapshot, candidate = route_fixture()
    router = CountingRouter()
    original = router.route_geometry

    async def shifted(coordinates, profile):
        result = await original(coordinates, profile)
        result["coordinates"][0][0] += 0.001
        return result

    router.route_geometry = shifted
    with pytest.raises(DomainError, match="snapped waypoint"):
        await RouteBuilder(router, MemoryStore(), 20).build(snapshot, candidate([0, 1, 2]))
