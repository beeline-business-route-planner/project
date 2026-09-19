from datetime import UTC, datetime

import httpx
import pytest

from beeline_backend.domain.errors import DependencyUnavailableError
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
