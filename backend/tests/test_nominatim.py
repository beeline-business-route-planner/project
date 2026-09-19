from __future__ import annotations

import httpx
import pytest

from beeline_backend.domain.errors import DependencyUnavailableError, DomainError
from beeline_backend.infrastructure.providers import NominatimGeocoder


@pytest.mark.asyncio
async def test_nominatim_uses_identifying_header_and_russian_search() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == "beeline-tests/1.0"
        assert request.url.params["q"] == "г. Москва, Тверская, 1, Москва"
        assert request.url.params["countrycodes"] == "ru"
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json=[{"lat": "55.757", "lon": "37.615"}])

    provider = NominatimGeocoder(
        "https://nominatim.test",
        "beeline-tests/1.0",
        timeout_seconds=1,
        min_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    assert await provider.geocode("г. Москва, Тверская, 1", "Москва") == (
        55.757,
        37.615,
    )


@pytest.mark.asyncio
async def test_nominatim_distinguishes_not_found_and_rate_limit() -> None:
    responses = iter(
        [
            httpx.Response(200, json=[]),
            httpx.Response(429, json={"error": "rate limited"}),
        ]
    )

    provider = NominatimGeocoder(
        "https://nominatim.test",
        "beeline-tests/1.0",
        timeout_seconds=1,
        min_interval_seconds=0,
        transport=httpx.MockTransport(lambda _request: next(responses)),
    )

    with pytest.raises(DomainError, match="Address was not found") as not_found:
        await provider.geocode("нет такого адреса", "Москва")
    assert not_found.value.code == "geocoding_not_found"

    with pytest.raises(DependencyUnavailableError) as rate_limited:
        await provider.geocode("адрес", "Москва")
    assert rate_limited.value.code == "geocoding_unavailable"
