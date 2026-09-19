from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
from datetime import datetime
from time import perf_counter
from typing import cast

import httpx

from beeline_backend.application.contracts import RouteMatrix, TravelCell
from beeline_backend.application.ports import GeocodingProvider, RoutingProvider
from beeline_backend.domain.errors import DependencyUnavailableError, DomainError


class DemoGeocoder:
    """Deterministic demo-only coordinates; never used as an external geocoder."""

    name = "demo_deterministic"

    async def geocode(self, address: str, region: str) -> tuple[float, float]:
        digest = hashlib.sha256(f"{region}|{address}".encode()).digest()
        latitude = 55.55 + int.from_bytes(digest[:4], "big") / 2**32 * 0.35
        longitude = 37.35 + int.from_bytes(digest[4:8], "big") / 2**32 * 0.55
        return latitude, longitude


class FallbackGeocoder:
    """Use a free primary geocoder and fall back to deterministic synthetic coordinates.

    The fallback is intended for synthetic hackathon datasets only. Production deployments
    should use a real geocoder or pre-validated coordinates.
    """

    name = "nominatim_with_demo_fallback"

    def __init__(self, primary: GeocodingProvider, fallback: GeocodingProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def geocode(self, address: str, region: str) -> tuple[float, float]:
        try:
            return await self._primary.geocode(address, region)
        except DomainError as exc:
            if exc.code != "geocoding_not_found":
                raise
        except DependencyUnavailableError:
            pass
        return await self._fallback.geocode(address, region)


class MissingGeocoder:
    name = "not_configured"

    async def geocode(self, address: str, region: str) -> tuple[float, float]:
        raise DependencyUnavailableError(
            "geocoding_required",
            "Coordinates are missing and no geocoding provider is configured",
            {"address": address, "region": region},
        )


class DgisGeocoder:
    name = "2gis_geocoder"

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport
        self._semaphore = asyncio.Semaphore(4)

    def _require_key(self) -> str:
        if not self._api_key:
            raise DependencyUnavailableError(
                "dgis_not_configured",
                "DGIS_API_KEY is required for the 2GIS geocoder",
                {"provider": self.name},
            )
        return self._api_key

    async def geocode(self, address: str, region: str) -> tuple[float, float]:
        key = self._require_key()
        try:
            async with self._semaphore, httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    f"{self._base_url}/3.0/items/geocode",
                    params={
                        "q": f"{address}, {region}" if region else address,
                        "fields": "items.point,items.geometry.centroid",
                        "locale": "ru_RU",
                        "page_size": "1",
                        "key": key,
                    },
                )
            if response.status_code in (401, 403):
                raise DependencyUnavailableError(
                    "dgis_geocoder_access_denied",
                    "The 2GIS key has no access to Geocoder API",
                    {"provider": self.name, "status_code": response.status_code},
                )
            if response.status_code == 429 or response.status_code >= 500:
                raise DependencyUnavailableError(
                    "geocoding_unavailable",
                    "2GIS Geocoder API is temporarily unavailable or rate-limited",
                    {"provider": self.name, "status_code": response.status_code},
                )
            response.raise_for_status()
        except DependencyUnavailableError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            raise DependencyUnavailableError(
                "geocoding_unavailable",
                "2GIS Geocoder API request failed",
                {"provider": self.name},
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise DependencyUnavailableError(
                "invalid_geocoding_response",
                "2GIS Geocoder API returned malformed JSON",
                {"provider": self.name},
            ) from exc
        meta = payload.get("meta") if isinstance(payload, dict) else None
        meta_code = meta.get("code") if isinstance(meta, dict) else None
        if meta_code in (401, 403):
            raise DependencyUnavailableError(
                "dgis_geocoder_access_denied",
                "The 2GIS key has no access to Geocoder API",
                {"provider": self.name, "provider_code": meta_code},
            )
        if meta_code == 404:
            raise DomainError(
                "geocoding_not_found",
                "Address was not found in 2GIS",
                {"address": address, "region": region, "provider": self.name},
            )
        if isinstance(meta_code, int) and meta_code != 200:
            raise DependencyUnavailableError(
                "geocoding_unavailable",
                "2GIS Geocoder API returned an error",
                {"provider": self.name, "provider_code": meta_code},
            )
        result = payload.get("result") if isinstance(payload, dict) else None
        items = result.get("items") if isinstance(result, dict) else None
        if not isinstance(items, list) or not items:
            raise DomainError(
                "geocoding_not_found",
                "Address was not found in 2GIS",
                {"address": address, "region": region, "provider": self.name},
            )
        first = items[0]
        point = first.get("point") if isinstance(first, dict) else None
        latitude = point.get("lat") if isinstance(point, dict) else None
        longitude = point.get("lon") if isinstance(point, dict) else None
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            geometry = first.get("geometry") if isinstance(first, dict) else None
            centroid = geometry.get("centroid") if isinstance(geometry, dict) else None
            parsed_centroid = _parse_wkt_point(centroid) if isinstance(centroid, str) else None
            if parsed_centroid is not None:
                longitude, latitude = parsed_centroid
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            raise DependencyUnavailableError(
                "invalid_geocoding_response",
                "2GIS Geocoder API returned invalid coordinates",
                {"provider": self.name},
            )
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise DependencyUnavailableError(
                "invalid_geocoding_response",
                "2GIS Geocoder API returned coordinates outside valid bounds",
                {"provider": self.name},
            )
        return float(latitude), float(longitude)


def _nominatim_query_candidates(address: str, region: str) -> list[str]:
    cleaned = " ".join(address.strip().split())
    region_cf = region.casefold().strip()

    def with_region(value: str) -> str:
        if not region_cf or region_cf in value.casefold():
            return value
        return f"{value}, {region}"

    candidates = [with_region(cleaned)]
    normalized = cleaned
    normalized = re.sub(r"^г\.?\s*москва\s*,?\s*", "Москва, ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bул\.?\s+", "улица ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bд\.?\s+", "дом ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d+)\s*с\s*(\d+)", r"\1, строение \2", normalized, flags=re.IGNORECASE)
    normalized = " ".join(normalized.split())
    normalized_query = with_region(normalized)
    if normalized_query not in candidates:
        candidates.append(normalized_query)
    return candidates


class NominatimGeocoder:
    """Free OSM geocoder with public-service rate limiting and explicit attribution metadata."""

    name = "nominatim_openstreetmap"

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout_seconds: float,
        min_interval_seconds: float,
        email: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._timeout = timeout_seconds
        self._min_interval = min_interval_seconds
        self._email = email
        self._transport = transport
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def _wait_for_rate_limit(self) -> None:
        loop = asyncio.get_running_loop()
        remaining = self._min_interval - (loop.time() - self._last_request_at)
        if remaining > 0:
            await asyncio.sleep(remaining)
        self._last_request_at = loop.time()

    async def geocode(self, address: str, region: str) -> tuple[float, float]:
        payload: object = []
        for query in _nominatim_query_candidates(address, region):
            params = {
                "q": query,
                "format": "jsonv2",
                "limit": "1",
                "countrycodes": "ru",
                "addressdetails": "1",
            }
            if self._email:
                params["email"] = self._email
            try:
                async with self._lock:
                    await self._wait_for_rate_limit()
                    async with httpx.AsyncClient(
                        timeout=self._timeout,
                        transport=self._transport,
                        headers={"User-Agent": self._user_agent},
                    ) as client:
                        response = await client.get(f"{self._base_url}/search", params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    raise DependencyUnavailableError(
                        "geocoding_unavailable",
                        "Nominatim is temporarily unavailable or rate-limited",
                        {"provider": self.name, "status_code": response.status_code},
                    )
                response.raise_for_status()
            except DependencyUnavailableError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                raise DependencyUnavailableError(
                    "geocoding_unavailable",
                    "Nominatim request failed",
                    {"provider": self.name},
                ) from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise DependencyUnavailableError(
                    "invalid_geocoding_response",
                    "Nominatim returned malformed JSON",
                    {"provider": self.name},
                ) from exc
            if isinstance(payload, list) and payload:
                break
        if not isinstance(payload, list) or not payload:
            raise DomainError(
                "geocoding_not_found",
                "Address was not found in OpenStreetMap",
                {"address": address, "region": region, "provider": self.name},
            )
        first = payload[0]
        if not isinstance(first, dict) or "lat" not in first or "lon" not in first:
            raise DependencyUnavailableError(
                "invalid_geocoding_response",
                "Nominatim returned an invalid response",
                {"provider": self.name},
            )
        try:
            latitude = float(cast(str, first["lat"]))
            longitude = float(cast(str, first["lon"]))
        except (TypeError, ValueError) as exc:
            raise DependencyUnavailableError(
                "invalid_geocoding_response",
                "Nominatim returned invalid coordinates",
                {"provider": self.name},
            ) from exc
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise DependencyUnavailableError(
                "invalid_geocoding_response",
                "Nominatim returned coordinates outside valid bounds",
                {"provider": self.name},
            )
        return latitude, longitude


def _haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> int:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return int(6_371_000 * 2 * math.asin(math.sqrt(value)))


class DemoRoutingProvider:
    name = "demo_haversine"

    def __init__(self, clock: object) -> None:
        self._clock = clock

    async def matrix(
        self, coordinates: list[tuple[float, float]], profile: str, departure_at: datetime
    ) -> RouteMatrix:
        speeds = {"driving": 25.0, "walking": 4.5, "cycling": 14.0, "transit": 18.0}
        speed = speeds.get(profile, 20.0)
        cells: list[list[TravelCell]] = []
        for origin in coordinates:
            row: list[TravelCell] = []
            for destination in coordinates:
                distance = _haversine_meters(origin, destination)
                duration = int(distance / (speed * 1000 / 3600)) if distance else 0
                row.append(TravelCell(duration_seconds=duration, distance_meters=distance))
            cells.append(row)
        now = self._clock.now()  # type: ignore[attr-defined]
        return RouteMatrix(
            provider=self.name,
            provider_version="haversine-v1",
            captured_at=now,
            profile=profile,
            cells=cells,
        )

    async def route_geometry(
        self, coordinates: list[tuple[float, float]], profile: str
    ) -> dict[str, object]:
        return {
            "type": "LineString",
            "coordinates": [[longitude, latitude] for latitude, longitude in coordinates],
            "provider": self.name,
        }


class DgisRoutingProvider:
    name = "2gis"

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        matrix_block_size: int,
        clock: object,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._block_size = min(matrix_block_size, 25)
        self._clock = clock
        self._transport = transport
        self._semaphore = asyncio.Semaphore(4)

    def _require_key(self) -> str:
        if not self._api_key:
            raise DependencyUnavailableError(
                "dgis_not_configured",
                "DGIS_API_KEY is required for the 2GIS routing adapter",
                {"provider": self.name},
            )
        return self._api_key

    async def _post(
        self,
        path: str,
        payload: dict[str, object],
        query: dict[str, str] | None = None,
    ) -> dict[str, object]:
        key = self._require_key()
        params = {"key": key, **(query or {})}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with self._semaphore, httpx.AsyncClient(
                    timeout=self._timeout,
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        f"{self._base_url}{path}",
                        params=params,
                        json=payload,
                    )
                if response.status_code in (401, 403):
                    raise DependencyUnavailableError(
                        "dgis_routing_access_denied",
                        "The 2GIS key has no access to the requested navigation API",
                        {"provider": self.name, "status_code": response.status_code},
                    )
                if response.status_code == 402:
                    raise DependencyUnavailableError(
                        "dgis_routing_quota_exceeded",
                        "The 2GIS key quota does not allow this navigation request",
                        {"provider": self.name, "status_code": response.status_code},
                    )
                if response.status_code == 204:
                    raise DomainError(
                        "no_route",
                        "2GIS did not find routes for the requested points",
                        {"provider": self.name},
                    )
                if response.status_code in (400, 422):
                    raise DependencyUnavailableError(
                        "dgis_routing_request_rejected",
                        "2GIS rejected the navigation request",
                        {"provider": self.name, "status_code": response.status_code},
                    )
                if response.status_code in (408, 429) or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "temporary 2GIS failure",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                try:
                    result = response.json()
                except ValueError as exc:
                    raise DependencyUnavailableError(
                        "invalid_routing_response",
                        "2GIS Routing API returned malformed JSON",
                        {"provider": self.name},
                    ) from exc
                if not isinstance(result, dict):
                    raise DependencyUnavailableError(
                        "invalid_routing_response",
                        "2GIS Routing API returned an invalid response shape",
                        {"provider": self.name},
                    )
                return result
            except (DependencyUnavailableError, DomainError):
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.2 * 2**attempt)
        raise DependencyUnavailableError(
            "routing_unavailable",
            "2GIS Routing API is unavailable",
            {"provider": self.name},
        ) from last_error

    async def matrix(
        self, coordinates: list[tuple[float, float]], profile: str, departure_at: datetime
    ) -> RouteMatrix:
        transport = _dgis_transport_profile(profile)
        size = len(coordinates)
        cells = [
            [TravelCell(duration_seconds=None, distance_meters=None) for _ in range(size)]
            for _ in range(size)
        ]
        blocks = [
            list(range(start, min(start + self._block_size, size)))
            for start in range(0, size, self._block_size)
        ]
        for source_indices in blocks:
            for target_indices in blocks:
                combined_indices = source_indices + target_indices
                payload: dict[str, object] = {
                    "points": [
                        {"lat": coordinates[index][0], "lon": coordinates[index][1]}
                        for index in combined_indices
                    ],
                    "sources": list(range(len(source_indices))),
                    "targets": list(range(len(source_indices), len(combined_indices))),
                    "start_time": departure_at.isoformat(),
                    "transport": transport,
                    "type": "jam",
                }
                response = await self._post(
                    "/get_dist_matrix", payload, {"version": "2.0"}
                )
                routes = response.get("routes")
                if not isinstance(routes, list):
                    raise DependencyUnavailableError(
                        "invalid_routing_response",
                        "2GIS distance matrix response has no routes",
                        {"provider": self.name},
                    )
                expected_route_count = len(source_indices) * len(target_indices)
                if len(routes) != expected_route_count:
                    raise DependencyUnavailableError(
                        "invalid_routing_response",
                        "2GIS distance matrix response has an invalid shape",
                        {"provider": self.name},
                    )
                seen_pairs: set[tuple[int, int]] = set()
                for route in routes:
                    if not isinstance(route, dict):
                        raise DependencyUnavailableError(
                            "invalid_routing_response",
                            "2GIS distance matrix contains an invalid route",
                            {"provider": self.name},
                        )
                    source_id = route.get("source_id")
                    target_id = route.get("target_id")
                    if (
                        not isinstance(source_id, int)
                        or isinstance(source_id, bool)
                        or not isinstance(target_id, int)
                        or isinstance(target_id, bool)
                        or source_id < 0
                        or source_id >= len(source_indices)
                    ):
                        raise DependencyUnavailableError(
                            "invalid_routing_response",
                            "2GIS distance matrix contains invalid route indices",
                            {"provider": self.name},
                        )
                    local_target = target_id - len(source_indices)
                    if local_target < 0 or local_target >= len(target_indices):
                        raise DependencyUnavailableError(
                            "invalid_routing_response",
                            "2GIS distance matrix contains invalid route indices",
                            {"provider": self.name},
                        )
                    pair = (source_id, local_target)
                    if pair in seen_pairs:
                        raise DependencyUnavailableError(
                            "invalid_routing_response",
                            "2GIS distance matrix contains duplicate routes",
                            {"provider": self.name},
                        )
                    seen_pairs.add(pair)
                    source_index = source_indices[source_id]
                    target_index = target_indices[local_target]
                    if route.get("status") == "OK":
                        duration = route.get("duration")
                        distance = route.get("distance")
                        if (
                            not isinstance(duration, (int, float))
                            or isinstance(duration, bool)
                            or not math.isfinite(duration)
                            or duration < 0
                            or not isinstance(distance, (int, float))
                            or isinstance(distance, bool)
                            or not math.isfinite(distance)
                            or distance < 0
                        ):
                            raise DependencyUnavailableError(
                                "invalid_routing_response",
                                "2GIS distance matrix contains invalid route metrics",
                                {"provider": self.name},
                            )
                        cells[source_index][target_index] = TravelCell(
                            duration_seconds=int(duration),
                            distance_meters=int(distance),
                        )
        return RouteMatrix(
            provider=self.name,
            provider_version="distance-matrix-2.0",
            captured_at=self._clock.now(),  # type: ignore[attr-defined]
            profile=profile,
            cells=cells,
        )

    async def route_geometry(
        self, coordinates: list[tuple[float, float]], profile: str
    ) -> dict[str, object]:
        transport = _dgis_transport_profile(profile)
        response = await self._post(
            "/routing/7.0.0/global",
            {
                "points": [
                    {
                        "type": "stop" if index in (0, len(coordinates) - 1) else "pref",
                        "lat": latitude,
                        "lon": longitude,
                        **({"start": True} if index == 0 else {}),
                    }
                    for index, (latitude, longitude) in enumerate(coordinates)
                ],
                "transport": transport,
                "output": "detailed",
                "locale": "ru",
                "alternative": 0,
            },
        )
        if response.get("status") != "OK":
            raise DomainError(
                "no_route",
                "2GIS did not return a route",
                {"provider": self.name, "provider_status": response.get("status")},
            )
        try:
            points = _dgis_geometry_points(response)
        except (OverflowError, ValueError) as exc:
            raise DependencyUnavailableError(
                "invalid_route_response",
                "2GIS route geometry is invalid",
                {"provider": self.name},
            ) from exc
        if len(points) < 2:
            raise DependencyUnavailableError(
                "invalid_route_response",
                "2GIS route geometry is missing",
                {"provider": self.name},
            )
        return {"type": "LineString", "coordinates": points, "provider": self.name}


def _dgis_geometry_points(value: object) -> list[list[float]]:
    selections: list[str] = []

    def collect(current: object) -> None:
        if isinstance(current, dict):
            selection = current.get("selection")
            if isinstance(selection, str) and selection.startswith("LINESTRING("):
                selections.append(selection)
            for child in current.values():
                collect(child)
        elif isinstance(current, list):
            for child in current:
                collect(child)

    collect(value.get("result") if isinstance(value, dict) else value)
    points: list[list[float]] = []
    for selection in selections:
        if not selection.endswith(")"):
            raise ValueError("invalid LINESTRING")
        content = selection.removeprefix("LINESTRING(").removesuffix(")")
        for raw_point in content.split(","):
            parts = raw_point.strip().split()
            if len(parts) < 2:
                raise ValueError("invalid LINESTRING point")
            point = [float(parts[0]), float(parts[1])]
            if (
                not all(math.isfinite(coordinate) for coordinate in point)
                or not -180 <= point[0] <= 180
                or not -90 <= point[1] <= 90
            ):
                raise ValueError("invalid LINESTRING coordinates")
            if not points or point != points[-1]:
                points.append(point)
    return points


def _parse_wkt_point(value: str) -> tuple[float, float] | None:
    if not value.startswith("POINT(") or not value.endswith(")"):
        return None
    parts = value.removeprefix("POINT(").removesuffix(")").strip().split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _dgis_transport_profile(profile: str) -> str:
    aliases = {
        "car": "driving",
        "cycling": "bicycle",
        "pedestrian": "walking",
        "transit": "public_transport",
    }
    normalized = aliases.get(profile, profile)
    supported = {
        "driving",
        "taxi",
        "truck",
        "walking",
        "bicycle",
        "scooter",
        "motorcycle",
        "public_transport",
    }
    if normalized not in supported:
        raise DomainError(
            "unsupported_routing_profile",
            "The routing profile is not supported by 2GIS",
            {"provider": DgisRoutingProvider.name, "profile": profile},
        )
    return normalized


class OsrmRoutingProvider:
    name = "osrm"

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        max_coordinates: int,
        clock: object,
        transport: httpx.AsyncBaseTransport | None = None,
        max_concurrency: int = 8,
        graph_fingerprint: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_coordinates = max_coordinates
        self._clock = clock
        self._transport = transport
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self.graph_fingerprint = graph_fingerprint
        self._data_version: str | None = None
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds, transport=transport, trust_env=False,
            limits=httpx.Limits(max_connections=max_concurrency, max_keepalive_connections=max_concurrency),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _validate_profile(profile: str) -> None:
        if profile != "driving":
            raise DomainError("unsupported_routing_profile", "The local graph supports driving only")

    @staticmethod
    def _coordinates(coordinates: list[tuple[float, float]]) -> str:
        return ";".join(f"{longitude:.6f},{latitude:.6f}" for latitude, longitude in coordinates)

    async def _request(self, path: str, params: dict[str, str]) -> dict[str, object]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with self._semaphore:
                    started = perf_counter()
                    try:
                        response = await self._client.get(f"{self._base_url}{path}", params=params)
                    finally:
                        logging.getLogger(__name__).info("routing_request", extra={"fields": {
                            "provider": self.name, "service": path.split("/")[1], "attempt": attempt+1,
                            "elapsed_ms": round((perf_counter()-started)*1000, 3),
                        }})
                if response.status_code >= 500 or response.status_code == 429:
                    raise httpx.HTTPStatusError("temporary OSRM failure", request=response.request, response=response)
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise DependencyUnavailableError(
                        "invalid_routing_response",
                        "OSRM returned malformed JSON",
                        {"provider": self.name},
                    ) from exc
                if not isinstance(payload, dict):
                    raise DependencyUnavailableError(
                        "invalid_routing_response",
                        "OSRM returned an invalid response shape",
                        {"provider": self.name},
                    )
                code = payload.get("code")
                if code != "Ok":
                    raise DomainError(
                        "routing_failed", f"OSRM returned {code}", {"provider_code": code}
                    )
                response.raise_for_status()
                data_version = payload.get("data_version")
                if isinstance(data_version, str):
                    if self._data_version is not None and self._data_version != data_version:
                        raise DependencyUnavailableError("routing_graph_changed", "OSRM graph changed; restart the API with its matching manifest")
                    self._data_version = data_version
                return payload
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.2 * 2**attempt)
        raise DependencyUnavailableError(
            "routing_unavailable", "OSRM is unavailable", {"provider": self.name}
        ) from last_error

    async def matrix(
        self, coordinates: list[tuple[float, float]], profile: str, departure_at: datetime
    ) -> RouteMatrix:
        self._validate_profile(profile)
        size = len(coordinates)
        cells = [[TravelCell(duration_seconds=None, distance_meters=None) for _ in range(size)] for _ in range(size)]
        block_size = max(1, self._max_coordinates // 2)
        blocks = [list(range(start, min(start + block_size, size))) for start in range(0, size, block_size)]
        provider_version = "unknown"
        for source_indices in blocks:
            for destination_indices in blocks:
                combined = [coordinates[index] for index in source_indices + destination_indices]
                source_count = len(source_indices)
                params = {
                    "annotations": "duration,distance",
                    "sources": ";".join(str(index) for index in range(source_count)),
                    "destinations": ";".join(
                        str(index) for index in range(source_count, len(combined))
                    ),
                }
                payload = await self._request(
                    f"/table/v1/{profile}/{self._coordinates(combined)}",
                    params,
                )
                provider_version = str(payload.get("data_version") or provider_version)
                durations = payload.get("durations")
                distances = payload.get("distances")
                expected_rows = len(source_indices)
                expected_columns = len(destination_indices)
                if (
                    not isinstance(durations, list)
                    or not isinstance(distances, list)
                    or len(durations) != expected_rows
                    or len(distances) != expected_rows
                    or any(
                        not isinstance(row, list) or len(row) != expected_columns
                        for row in durations + distances
                    )
                ):
                    raise DependencyUnavailableError(
                        "invalid_routing_response",
                        "OSRM matrix response has an invalid shape",
                        {"provider": self.name},
                    )
                for row_index, source_index in enumerate(source_indices):
                    duration_row = durations[row_index]
                    distance_row = distances[row_index]
                    for column_index, destination_index in enumerate(destination_indices):
                        duration = duration_row[column_index]
                        distance = distance_row[column_index]
                        metrics_are_valid = (
                            duration is None
                            and distance is None
                            or isinstance(duration, (int, float))
                            and not isinstance(duration, bool)
                            and math.isfinite(duration)
                            and duration >= 0
                            and isinstance(distance, (int, float))
                            and not isinstance(distance, bool)
                            and math.isfinite(distance)
                            and distance >= 0
                        )
                        if not metrics_are_valid:
                            raise DependencyUnavailableError(
                                "invalid_routing_response",
                                "OSRM matrix response contains invalid metrics",
                                {"provider": self.name},
                            )
                        cells[source_index][destination_index] = TravelCell(
                            duration_seconds=None if duration is None else int(duration),
                            distance_meters=None if distance is None else int(distance),
                        )
        return RouteMatrix(
            provider=self.name,
            provider_version=self.graph_fingerprint or provider_version,
            captured_at=self._clock.now(),  # type: ignore[attr-defined]
            profile=profile,
            cells=cells,
        )

    async def route_geometry(
        self, coordinates: list[tuple[float, float]], profile: str
    ) -> dict[str, object]:
        self._validate_profile(profile)
        payload = await self._request(
            f"/route/v1/{profile}/{self._coordinates(coordinates)}",
            {"overview": "full", "geometries": "geojson", "alternatives": "false"},
        )
        routes = payload.get("routes")
        if not isinstance(routes, list) or not routes:
            raise DomainError("no_route", "OSRM did not return a route")
        first = routes[0]
        if not isinstance(first, dict) or "geometry" not in first:
            raise DomainError("invalid_route_response", "OSRM route geometry is missing")
        geometry = first["geometry"]
        if not isinstance(geometry, dict):
            raise DomainError("invalid_route_response", "OSRM route geometry is invalid")
        result = dict(geometry)
        result["provider"] = self.name
        result["distance_meters"] = first.get("distance")
        result["duration_seconds"] = first.get("duration")
        points = result.get("coordinates")
        if isinstance(points, list) and len(points) == 1 and first.get("distance") == 0:
            result["coordinates"] = [points[0], points[0]]
        return result


class HybridRoutingProvider:
    """Compatibility strategy: local OSRM owns matrix and primary geometry.

    Commercial refinement is never called implicitly during planning or reads.
    Legacy constructor arguments are accepted to ease migration of integrations.
    """

    name = "hybrid_osrm"

    def __init__(
        self,
        matrix_provider: RoutingProvider,
        geometry_provider: RoutingProvider | None = None,
        fallback_geometry_provider: RoutingProvider | None = None,
        dgis_max_route_points: int = 5,
    ) -> None:
        self._matrix_provider = matrix_provider
        self.graph_fingerprint = getattr(matrix_provider, "graph_fingerprint", None)

    async def matrix(
        self, coordinates: list[tuple[float, float]], profile: str, departure_at: datetime
    ) -> RouteMatrix:
        return await self._matrix_provider.matrix(coordinates, profile, departure_at)

    async def route_geometry(
        self, coordinates: list[tuple[float, float]], profile: str
    ) -> dict[str, object]:
        geometry = await self._matrix_provider.route_geometry(coordinates, profile)
        result = dict(geometry)
        result["routing_strategy"] = self.name
        return result

    async def aclose(self) -> None:
        close = getattr(self._matrix_provider, "aclose", None)
        if close is not None:
            await close()


class YandexRoutingProvider:
    name = "yandex"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def _require_key(self) -> str:
        if not self._api_key:
            raise DependencyUnavailableError(
                "yandex_not_configured",
                "YANDEX_API_KEY is required for the Yandex routing adapter",
                {"provider": self.name},
            )
        return self._api_key

    async def matrix(
        self, coordinates: list[tuple[float, float]], profile: str, departure_at: datetime
    ) -> RouteMatrix:
        self._require_key()
        raise DependencyUnavailableError(
            "yandex_contract_pending",
            "Yandex adapter is configured but its licensed API contract is not enabled",
            {"provider": self.name, "departure_at": departure_at.isoformat()},
        )

    async def route_geometry(
        self, coordinates: list[tuple[float, float]], profile: str
    ) -> dict[str, object]:
        self._require_key()
        raise DependencyUnavailableError(
            "yandex_contract_pending",
            "Yandex geometry contract must be enabled for the selected commercial API",
        )
