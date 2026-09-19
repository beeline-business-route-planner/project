from datetime import UTC, datetime

import httpx
import pytest

from beeline_backend.domain.errors import DependencyUnavailableError, DomainError
from beeline_backend.infrastructure.providers import OsrmRoutingProvider


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 17, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_osrm_matrix_preserves_null_and_direction() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "/table/v1/driving/" in request.url.path
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "data_version": "graph-1",
                "durations": [[0, 10], [20, None]],
                "distances": [[0, 100], [120, None]],
            },
        )

    provider = OsrmRoutingProvider(
        "https://osrm.test",
        timeout_seconds=1,
        max_coordinates=4,
        clock=FixedClock(),
        transport=httpx.MockTransport(handler),
    )
    matrix = await provider.matrix(
        [(55.7, 37.6), (55.8, 37.7)], "driving", FixedClock().now()
    )
    assert matrix.provider_version == "graph-1"
    assert matrix.cells[0][1].duration_seconds == 10
    assert matrix.cells[1][0].duration_seconds == 20
    assert matrix.cells[1][1].duration_seconds is None


@pytest.mark.asyncio
async def test_osrm_matrix_rejects_invalid_shape() -> None:
    provider = OsrmRoutingProvider(
        "https://osrm.test",
        timeout_seconds=1,
        max_coordinates=4,
        clock=FixedClock(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "code": "Ok",
                    "durations": [[0, 10]],
                    "distances": [[0, 100], [120, 0]],
                },
            )
        ),
    )

    with pytest.raises(DependencyUnavailableError) as invalid:
        await provider.matrix(
            [(55.7, 37.6), (55.8, 37.7)], "driving", FixedClock().now()
        )
    assert invalid.value.code == "invalid_routing_response"


@pytest.mark.asyncio
async def test_osrm_block_matrix_preserves_global_indices_and_limits() -> None:
    calls = []

    def handler(request):
        points = request.url.path.rsplit("/", 1)[1].split(";")
        assert len(points) <= 4
        global_indices = [round(float(point.split(",")[0])-37) for point in points]
        origins = [global_indices[int(index)] for index in request.url.params["sources"].split(";")]
        destinations = [global_indices[int(index)] for index in request.url.params["destinations"].split(";")]
        cells = [[0 if a == b else a*100+b for b in destinations] for a in origins]
        calls.append(request)
        return httpx.Response(200, json={"code": "Ok", "data_version": "graph-1", "durations": cells,
                                        "distances": [[value*10 for value in row] for row in cells]})
    provider = OsrmRoutingProvider("https://osrm.test", 1, 4, FixedClock(), transport=httpx.MockTransport(handler))
    try:
        matrix = await provider.matrix([(55.7, 37+i) for i in range(5)], "driving", FixedClock().now())
        assert len(calls) == 9
        assert matrix.cells[4][1].duration_seconds == 401
        assert matrix.cells[1][4].distance_meters == 1040
        assert matrix.cells[3][3].duration_seconds == 0
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_osrm_rejects_graph_change_between_blocks() -> None:
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json={"code": "Ok", "data_version": f"graph-{count}", "durations": [[0]], "distances": [[0]]})
    provider = OsrmRoutingProvider("https://osrm.test", 1, 2, FixedClock(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(DependencyUnavailableError) as failure:
            await provider.matrix([(55.7, 37.6), (55.8, 37.7)], "driving", FixedClock().now())
        assert failure.value.code == "routing_graph_changed"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_osrm_route_preserves_metrics_and_rejects_unsupported_profile() -> None:
    provider = OsrmRoutingProvider("https://osrm.test", 1, 4, FixedClock(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"code": "Ok", "routes": [{"geometry": {"type": "LineString", "coordinates": [[37.6, 55.7], [37.7, 55.8]]}, "distance": 125.5, "duration": 17.2}]})))
    try:
        route = await provider.route_geometry([(55.7, 37.6), (55.8, 37.7)], "driving")
        assert route["distance_meters"] == 125.5
        assert route["duration_seconds"] == 17.2
        with pytest.raises(DomainError) as failure:
            await provider.route_geometry([(55.7, 37.6), (55.8, 37.7)], "transit")
        assert failure.value.code == "unsupported_routing_profile"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_osrm_rejects_malformed_json() -> None:
    provider = OsrmRoutingProvider(
        "https://osrm.test",
        timeout_seconds=1,
        max_coordinates=4,
        clock=FixedClock(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"not-json")
        ),
    )

    with pytest.raises(DependencyUnavailableError) as invalid:
        await provider.route_geometry([(55.7, 37.6), (55.8, 37.7)], "driving")
    assert invalid.value.code == "invalid_routing_response"
