from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
import pytest

from beeline_backend.config import Settings
from beeline_backend.domain.errors import DependencyUnavailableError
from beeline_backend.infrastructure.providers import DgisGeocoder, DgisRoutingProvider
from beeline_backend.presentation.api import create_app


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 17, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_httpx_info_log_does_not_expose_dgis_key(caplog: pytest.LogCaptureFixture) -> None:
    synthetic_key = "synthetic-secret-dgis-key"
    create_app(
        Settings(
            app_env="test",
            database_url="sqlite+aiosqlite:///:memory:",
            geocoder_mode="demo",
            routing_provider="demo",
        )
    )
    provider = DgisGeocoder(
        "https://catalog.api.2gis.test",
        synthetic_key,
        timeout_seconds=1,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "meta": {"code": 200},
                    "result": {"items": [{"point": {"lat": 55.757, "lon": 37.615}}]},
                },
            )
        ),
    )

    caplog.set_level(logging.INFO)
    await provider.geocode("Тверская, 1", "Москва")

    assert synthetic_key not in caplog.text
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


@pytest.mark.asyncio
async def test_dgis_geocoder_parses_point_without_exposing_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3.0/items/geocode"
        assert request.url.params["key"] == "test-key"
        assert request.url.params["q"] == "Тверская, 1, Москва"
        assert request.url.params["fields"] == "items.point,items.geometry.centroid"
        assert request.url.params["locale"] == "ru_RU"
        assert request.url.params["page_size"] == "1"
        return httpx.Response(
            200,
            json={
                "meta": {"code": 200},
                "result": {"items": [{"point": {"lat": 55.757, "lon": 37.615}}]},
            },
        )

    provider = DgisGeocoder(
        "https://catalog.api.2gis.test",
        "test-key",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    assert await provider.geocode("Тверская, 1", "Москва") == (55.757, 37.615)


@pytest.mark.asyncio
async def test_dgis_geocoder_uses_wkt_centroid_when_point_is_absent() -> None:
    provider = DgisGeocoder(
        "https://catalog.api.2gis.test",
        "test-key",
        timeout_seconds=1,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "meta": {"code": 200},
                    "result": {
                        "items": [{"geometry": {"centroid": "POINT(37.615 55.757)"}}]
                    },
                },
            )
        ),
    )
    assert await provider.geocode("Тверская, 1", "Москва") == (55.757, 37.615)


@pytest.mark.asyncio
async def test_dgis_geocoder_handles_error_inside_http_200() -> None:
    provider = DgisGeocoder(
        "https://catalog.api.2gis.test",
        "test-key",
        timeout_seconds=1,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "meta": {
                        "code": 403,
                        "error": {"type": "accessDenied", "message": "denied"},
                    }
                },
            )
        ),
    )
    with pytest.raises(DependencyUnavailableError) as denied:
        await provider.geocode("Тверская, 1", "Москва")
    assert denied.value.code == "dgis_geocoder_access_denied"


@pytest.mark.asyncio
async def test_dgis_geocoder_reports_missing_scope() -> None:
    provider = DgisGeocoder(
        "https://catalog.api.2gis.test",
        "test-key",
        timeout_seconds=1,
        transport=httpx.MockTransport(lambda _request: httpx.Response(403)),
    )
    with pytest.raises(DependencyUnavailableError) as denied:
        await provider.geocode("Тверская, 1", "Москва")
    assert denied.value.code == "dgis_geocoder_access_denied"
    assert "test-key" not in str(denied.value.details)


@pytest.mark.asyncio
async def test_dgis_matrix_and_route_geometry_contracts() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/get_dist_matrix":
            assert request.url.params["version"] == "2.0"
            return httpx.Response(
                200,
                json={
                    "routes": [
                        {
                            "status": "OK",
                            "source_id": 0,
                            "target_id": 2,
                            "duration": 0,
                            "distance": 0,
                        },
                        {
                            "status": "OK",
                            "source_id": 0,
                            "target_id": 3,
                            "duration": 100,
                            "distance": 1500,
                        },
                        {
                            "status": "OK",
                            "source_id": 1,
                            "target_id": 2,
                            "duration": 120,
                            "distance": 1700,
                        },
                        {
                            "status": "ROUTE_NOT_FOUND",
                            "source_id": 1,
                            "target_id": 3,
                            "duration": 0,
                            "distance": 0,
                        },
                    ]
                },
            )
        assert request.url.path == "/routing/7.0.0/global"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "result": [
                    {
                        "maneuvers": [
                            {
                                "outcoming_path": {
                                    "geometry": [
                                        {"selection": "LINESTRING(37.6 55.7, 37.65 55.75)"},
                                        {"selection": "LINESTRING(37.65 55.75, 37.7 55.8)"},
                                    ]
                                }
                            }
                        ]
                    }
                ],
            },
        )

    provider = DgisRoutingProvider(
        "https://routing.api.2gis.test",
        "test-key",
        timeout_seconds=1,
        matrix_block_size=25,
        clock=FixedClock(),
        transport=httpx.MockTransport(handler),
    )
    coordinates = [(55.7, 37.6), (55.8, 37.7)]
    matrix = await provider.matrix(coordinates, "driving", FixedClock().now())
    assert matrix.cells[0][1].duration_seconds == 100
    assert matrix.cells[1][0].duration_seconds == 120
    assert matrix.cells[1][1].duration_seconds is None

    geometry = await provider.route_geometry(coordinates, "driving")
    assert geometry == {
        "type": "LineString",
        "coordinates": [[37.6, 55.7], [37.65, 55.75], [37.7, 55.8]],
        "provider": "2gis",
    }
