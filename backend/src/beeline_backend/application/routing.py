"""Persistable routing artifacts. Rendering a saved plan never calls a provider."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field, FiniteFloat, field_validator

from beeline_backend.application.contracts import PlanningSnapshot
from beeline_backend.application.ports import RoutingProvider
from beeline_backend.domain.errors import ConflictError, DomainError
from beeline_backend.domain.model import Assignment, PlanCandidate

logger = logging.getLogger(__name__)
Coordinate = tuple[float, float]  # GeoJSON: longitude, latitude
EARTH_RADIUS = 6_371_008.8


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def canonical_point(latitude: float, longitude: float) -> Coordinate:
    # Exactly the same precision as the OSRM request serialization.
    return float(f"{longitude:.6f}"), float(f"{latitude:.6f}")


class LineString(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=2)

    @field_validator("coordinates", mode="before")
    @classmethod
    def numeric_coordinates(cls, value: object) -> object:
        if not isinstance(value, list) or any(
            not isinstance(point, (list, tuple))
            or len(point) != 2
            or any(
                isinstance(number, bool) or not isinstance(number, (int, float)) for number in point
            )
            for point in value
        ):
            raise ValueError("Coordinates must contain numeric longitude/latitude pairs")
        return value

    @field_validator("coordinates")
    @classmethod
    def valid_coordinates(cls, points: list[Coordinate]) -> list[Coordinate]:
        if any(not -180 <= lon <= 180 or not -90 <= lat <= 90 for lon, lat in points):
            raise ValueError("Coordinates are outside longitude/latitude bounds")
        return points


class SegmentData(BaseModel):
    cache_id: UUID
    key: str
    provider: str
    graph_fingerprint: str
    profile: str
    origin: Coordinate
    destination: Coordinate
    geometry: LineString
    distance_meters: FiniteFloat = Field(ge=0)
    duration_seconds: FiniteFloat = Field(ge=0)
    metrics_source: Literal["route", "matrix"] = "route"

    @field_validator("distance_meters", "duration_seconds", mode="before")
    @classmethod
    def numeric_metrics(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Routing metrics must be numbers")
        return value


class RouteStop(BaseModel):
    sequence: int
    location_id: UUID
    request_id: UUID | None = None
    coordinates: Coordinate
    snapped_coordinates: Coordinate


class RouteSegment(BaseModel):
    sequence: int
    key: str
    from_location_id: UUID
    to_location_id: UUID
    distance_meters: float
    duration_seconds: float
    metrics_source: Literal["route", "matrix"]
    point_start: int
    point_end: int


class RouteOverview(BaseModel):
    engineer_id: UUID
    profile: str = "driving"
    route_status: Literal["ready", "empty"]
    provider: str
    graph_fingerprint: str
    geometry: LineString | None
    distance_meters: FiniteFloat = Field(ge=0)
    duration_seconds: FiniteFloat = Field(ge=0)


class RouteDetailed(RouteOverview):
    stops: list[RouteStop]
    segments: list[RouteSegment]


class OverviewResponse(BaseModel):
    plan_id: UUID
    revision: str
    status: str
    routes: list[RouteOverview]


class DetailedResponse(RouteDetailed):
    plan_id: UUID
    revision: str
    status: str


@dataclass(frozen=True)
class BuiltRoute:
    detailed: RouteDetailed
    overview: RouteOverview
    cache_ids: tuple[UUID, ...]

    @property
    def revision(self) -> str:
        return digest(
            [self.detailed.model_dump(mode="json"), self.overview.model_dump(mode="json")]
        )


@dataclass(frozen=True)
class RouteBuild:
    routes: dict[UUID, BuiltRoute]
    segments_reused: int
    segments_calculated: int

    @property
    def legacy_geometries(self) -> dict[UUID, dict[str, object]]:
        return {
            engineer_id: {
                **route.detailed.geometry.model_dump(mode="json"),
                "provider": route.detailed.provider,
            }
            for engineer_id, route in self.routes.items()
            if route.detailed.geometry is not None
        }


class SegmentStore(Protocol):
    async def get_many(self, keys: list[str]) -> dict[str, SegmentData]: ...
    async def put(self, segment: SegmentData) -> None: ...


def segment_key(
    provider: str,
    graph: str,
    profile: str,
    origin: Coordinate,
    destination: Coordinate,
    options: dict[str, object],
) -> str:
    return digest(
        {
            "schema": 1,
            "provider": provider,
            "graph": graph,
            "profile": profile,
            "origin": origin,
            "destination": destination,
            "options": options,
        }
    )


def _angle(a: Coordinate, b: Coordinate) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def _bearing(a: Coordinate, b: Coordinate) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    return math.atan2(
        math.sin(lon2 - lon1) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1),
    )


def point_segment_distance(point: Coordinate, start: Coordinate, end: Coordinate) -> float:
    """Distance to a minor great-circle arc on a sphere, in ground metres."""
    length = _angle(start, end)
    ap = _angle(start, point)
    if length < 1e-12:
        return EARTH_RADIUS * ap
    bearing_delta = _bearing(start, point) - _bearing(start, end)
    along = math.atan2(math.sin(ap) * math.cos(bearing_delta), math.cos(ap))
    if along <= 0:
        return EARTH_RADIUS * ap
    if along >= length:
        return EARTH_RADIUS * _angle(end, point)
    return EARTH_RADIUS * abs(
        math.asin(max(-1.0, min(1.0, math.sin(ap) * math.sin(bearing_delta))))
    )


def simplify(points: list[Coordinate], tolerance_meters: float) -> list[Coordinate]:
    """Iterative Douglas–Peucker, preserving endpoints; spherical metre tolerance."""
    if tolerance_meters <= 0 or len(points) <= 2:
        return list(points)
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        start, end = pending.pop()
        if end <= start + 1:
            continue
        index, distance = max(
            (
                (i, point_segment_distance(points[i], points[start], points[end]))
                for i in range(start + 1, end)
            ),
            key=lambda value: value[1],
        )
        if distance > tolerance_meters:
            keep.add(index)
            pending.extend(((start, index), (index, end)))
    return [points[index] for index in sorted(keep)]


class RouteBuilder:
    def __init__(
        self,
        provider: RoutingProvider,
        store: SegmentStore,
        tolerance_meters: float,
        concurrency: int = 8,
    ) -> None:
        self.provider = provider
        self.store = store
        self.tolerance = tolerance_meters
        self.concurrency = concurrency
        self._limit = asyncio.Semaphore(concurrency)
        self._build_limit = asyncio.Semaphore(2)
        self._flights: dict[str, asyncio.Task[SegmentData]] = {}

    async def build(self, snapshot: PlanningSnapshot, candidate: PlanCandidate) -> RouteBuild:
        async with self._build_limit:
            return await self._build(snapshot, candidate)

    async def _build(self, snapshot: PlanningSnapshot, candidate: PlanCandidate) -> RouteBuild:
        travel = snapshot.travel_by_profile["driving"]
        provider = travel.provider
        graph = travel.provider_version
        active_graph = getattr(self.provider, "graph_fingerprint", None)
        if provider == "osrm" and active_graph is not None and active_graph != graph:
            raise ConflictError(
                "routing_graph_changed",
                "Create a new plan before manually editing a plan from another graph",
            )
        # Dynamic commercial data must not become an indefinitely reusable static graph.
        if provider not in {"osrm", "demo_haversine"}:
            graph = digest([graph, travel.captured_at.isoformat()])
        options: dict[str, object] = {
            "geometries": "geojson",
            "overview": "full",
            "alternatives": False,
        }
        locations = {item.id: item for item in snapshot.locations}
        indices = {value: i for i, value in enumerate(snapshot.location_ids)}
        by_engineer: dict[UUID, list[Assignment]] = defaultdict(list)
        inputs: dict[str, tuple[Coordinate, Coordinate, Assignment]] = {}
        keys: dict[tuple[UUID, int], str] = {}
        for item in candidate.assignments:
            a, b = locations[item.from_location_id], locations[item.location_id]
            origin, destination = (
                canonical_point(a.latitude, a.longitude),
                canonical_point(b.latitude, b.longitude),
            )
            key = segment_key(provider, graph, "driving", origin, destination, options)
            keys[item.engineer_id, item.position] = key
            inputs[key] = origin, destination, item
            by_engineer[item.engineer_id].append(item)
        segments = await self.store.get_many(list(inputs))
        reused = len(segments)
        missing = iter(key for key in inputs if key not in segments)
        calculated = 0
        owned_tasks: list[asyncio.Task[SegmentData]] = []

        async def calculate(key: str) -> SegmentData:
            origin, destination, assignment = inputs[key]
            async with self._limit:
                raw = await self.provider.route_geometry(
                    [(origin[1], origin[0]), (destination[1], destination[0])], "driving"
                )
            try:
                geometry = LineString.model_validate(raw)
                cell = travel.cells[indices[assignment.from_location_id]][
                    indices[assignment.location_id]
                ]
                distance, duration = raw.get("distance_meters"), raw.get("duration_seconds")
                source: Literal["route", "matrix"] = "route"
                if distance is None or duration is None:
                    if provider == "osrm":
                        raise ValueError("OSRM segment metrics are required")
                    distance, duration, source = (
                        cell.distance_meters,
                        cell.duration_seconds,
                        "matrix",
                    )
                result = SegmentData.model_validate(
                    {
                        "cache_id": uuid5(NAMESPACE_URL, "beeline:route:" + key),
                        "key": key,
                        "provider": provider,
                        "graph_fingerprint": graph,
                        "profile": "driving",
                        "origin": origin,
                        "destination": destination,
                        "geometry": geometry,
                        "distance_meters": distance,
                        "duration_seconds": duration,
                        "metrics_source": source,
                    }
                )
            except (ValueError, TypeError) as exc:
                raise DomainError(
                    "invalid_route_response", "Invalid route geometry or metrics"
                ) from exc
            await self.store.put(result)
            return result

        async def worker() -> None:
            nonlocal calculated, reused
            for key in missing:
                task = self._flights.get(key)
                if task is None:
                    task = asyncio.create_task(calculate(key))
                    self._flights[key] = task
                    owned_tasks.append(task)

                    def finished(done: asyncio.Task[SegmentData], current: str = key) -> None:
                        if self._flights.get(current) is done:
                            self._flights.pop(current)
                        if not done.cancelled():
                            done.exception()  # consume errors if the initiating HTTP request was cancelled

                    task.add_done_callback(finished)
                    calculated += 1
                else:
                    reused += 1
                segments[key] = await asyncio.shield(task)

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(self.concurrency, len(inputs) - len(segments)))
        ]
        try:
            if workers:
                await asyncio.gather(*workers)
        finally:
            for task in workers:
                if not task.done():
                    task.cancel()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            # Keep the build admission slot until owned work finishes, even on cancellation.
            # This bounds outstanding provider tasks across cancelled HTTP requests.
            if owned_tasks:
                await asyncio.gather(*owned_tasks, return_exceptions=True)

        routes: dict[UUID, BuiltRoute] = {}
        for engineer in snapshot.engineers:
            ordered = sorted(by_engineer[engineer.id], key=lambda item: item.position)
            full: list[Coordinate] = []
            overview: list[Coordinate] = []
            stops: list[RouteStop] = []
            legs: list[RouteSegment] = []
            ids: list[UUID] = []
            for item in ordered:
                segment = segments[keys[item.engineer_id, item.position]]
                points = segment.geometry.coordinates
                if full and full[-1] != points[0]:
                    raise DomainError(
                        "route_snapping_discontinuity",
                        "Adjacent road segments do not share a snapped waypoint",
                    )
                if not full:
                    a = locations[item.from_location_id]
                    stops.append(
                        RouteStop(
                            sequence=0,
                            location_id=a.id,
                            coordinates=(a.longitude, a.latitude),
                            snapped_coordinates=points[0],
                        )
                    )
                point_start = max(0, len(full) - 1)
                full.extend(points[1:] if full else points)
                reduced = simplify(points, self.tolerance)
                overview.extend(reduced[1:] if overview else reduced)
                b = locations[item.location_id]
                stops.append(
                    RouteStop(
                        sequence=item.position,
                        location_id=b.id,
                        request_id=item.request_id,
                        coordinates=(b.longitude, b.latitude),
                        snapped_coordinates=points[-1],
                    )
                )
                legs.append(
                    RouteSegment(
                        sequence=item.position,
                        key=segment.key,
                        from_location_id=item.from_location_id,
                        to_location_id=item.location_id,
                        distance_meters=segment.distance_meters,
                        duration_seconds=segment.duration_seconds,
                        metrics_source=segment.metrics_source,
                        point_start=point_start,
                        point_end=len(full) - 1,
                    )
                )
                ids.append(segment.cache_id)
            detail = RouteDetailed(
                engineer_id=engineer.id,
                route_status="ready" if ordered else "empty",
                provider=provider,
                graph_fingerprint=graph,
                geometry=LineString(coordinates=full) if full else None,
                distance_meters=sum(x.distance_meters for x in legs),
                duration_seconds=sum(x.duration_seconds for x in legs),
                stops=stops,
                segments=legs,
            )
            summary = RouteOverview.model_validate(detail.model_dump())
            summary.geometry = LineString(coordinates=overview) if overview else None
            routes[engineer.id] = BuiltRoute(detail, summary, tuple(ids))
        logger.info(
            "route_build",
            extra={
                "fields": {
                    "segments_reused": reused,
                    "segments_calculated": calculated,
                    "graph_fingerprint": graph,
                    "engineers": len(routes),
                    "input_version": snapshot.input_version,
                }
            },
        )
        return RouteBuild(routes, reused, calculated)

    async def aclose(self) -> None:
        tasks = list(self._flights.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
