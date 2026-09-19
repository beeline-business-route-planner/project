from __future__ import annotations

from datetime import UTC, datetime

import pytest

from beeline_backend.application.contracts import RouteMatrix
from beeline_backend.domain.errors import DependencyUnavailableError, DomainError
from beeline_backend.infrastructure.providers import FallbackGeocoder, HybridRoutingProvider


class StubGeocoder:
    def __init__(self, result: tuple[float, float] | Exception) -> None:
        self.result = result

    async def geocode(self, address: str, region: str) -> tuple[float, float]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class StubRouter:
    def __init__(self, provider: str, geometry_error: Exception | None = None) -> None:
        self.provider = provider
        self.geometry_error = geometry_error
        self.matrix_calls = 0
        self.geometry_calls = 0

    async def matrix(self, coordinates, profile, departure_at):
        self.matrix_calls += 1
        return RouteMatrix(
            provider=self.provider,
            provider_version="test",
            captured_at=datetime(2026, 8, 17, tzinfo=UTC),
            profile=profile,
            cells=[],
        )

    async def route_geometry(self, coordinates, profile):
        self.geometry_calls += 1
        if self.geometry_error is not None:
            raise self.geometry_error
        return {"type": "LineString", "coordinates": [[37.6, 55.7]], "provider": self.provider}


@pytest.mark.asyncio
async def test_fallback_geocoder_uses_demo_when_primary_cannot_find_address() -> None:
    geocoder = FallbackGeocoder(
        StubGeocoder(DomainError("geocoding_not_found", "missing")),
        StubGeocoder((55.7, 37.6)),
    )
    assert await geocoder.geocode("synthetic", "Москва") == (55.7, 37.6)


@pytest.mark.asyncio
async def test_hybrid_router_uses_osrm_for_matrix_and_2gis_for_short_geometry() -> None:
    osrm = StubRouter("osrm")
    dgis = StubRouter("2gis")
    router = HybridRoutingProvider(osrm, dgis, osrm, dgis_max_route_points=5)

    matrix = await router.matrix([(55.7, 37.6)], "driving", datetime.now(UTC))
    geometry = await router.route_geometry([(55.7, 37.6), (55.8, 37.7)], "driving")

    assert matrix.provider == "osrm"
    assert osrm.matrix_calls == 1
    assert dgis.geometry_calls == 1
    assert geometry["provider"] == "2gis"
    assert geometry["routing_strategy"] == "hybrid_osrm_2gis"


@pytest.mark.asyncio
async def test_hybrid_router_falls_back_to_osrm_when_2gis_is_unavailable() -> None:
    osrm = StubRouter("osrm")
    dgis = StubRouter(
        "2gis",
        DependencyUnavailableError("dgis_routing_access_denied", "quota"),
    )
    router = HybridRoutingProvider(osrm, dgis, osrm, dgis_max_route_points=5)

    geometry = await router.route_geometry([(55.7, 37.6), (55.8, 37.7)], "driving")

    assert geometry["provider"] == "osrm"
    assert geometry["fallback_from"] == "2gis"
    assert geometry["fallback_reason"] == "dgis_routing_access_denied"


@pytest.mark.asyncio
async def test_hybrid_router_skips_2gis_when_route_exceeds_demo_point_budget() -> None:
    osrm = StubRouter("osrm")
    dgis = StubRouter("2gis")
    router = HybridRoutingProvider(osrm, dgis, osrm, dgis_max_route_points=5)
    coordinates = [(55.7 + i / 1000, 37.6 + i / 1000) for i in range(6)]

    geometry = await router.route_geometry(coordinates, "driving")

    assert dgis.geometry_calls == 0
    assert geometry["provider"] == "osrm"
    assert geometry["fallback_reason"] == "dgis_demo_point_budget"
