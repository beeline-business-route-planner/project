import asyncio
from decimal import Decimal, InvalidOperation
from time import monotonic

import httpx

from src.config import cfg
from src.core.geocoding.client import GeocodingClient
from src.core.geocoding.dto import Coordinates
from src.core.geocoding.exc import AddressNotFoundError, GeocodingUnavailableError
from src.core.geocoding.normalizer import RussianAddressNormalizer


class GeocodingService:
    """Геокодирует адреса через Nominatim с кэшем и ограничением частоты запросов."""

    def __init__(self, client: GeocodingClient) -> None:
        self._client = client
        self._cache: dict[str, Coordinates] = {}
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def geocode(self, address: str) -> Coordinates:
        normalized_address = " ".join(address.split())
        cached = self._cache.get(normalized_address)
        if cached is not None:
            return cached

        async with self._lock:
            cached = self._cache.get(normalized_address)
            if cached is not None:
                return cached

            for query in RussianAddressNormalizer.queries(normalized_address):
                elapsed = monotonic() - self._last_request_at
                delay = cfg.geocoding.min_request_interval_seconds - elapsed
                if delay > 0:
                    await asyncio.sleep(delay)

                try:
                    response = await self._client.get().get(
                        "/search",
                        params={
                            "q": query,
                            "format": "jsonv2",
                            "limit": 1,
                            "countrycodes": cfg.geocoding.country_codes,
                        },
                    )
                    self._last_request_at = monotonic()
                    response.raise_for_status()
                    payload = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    raise GeocodingUnavailableError("Сервис геокодирования недоступен") from exc

                if not isinstance(payload, list):
                    raise GeocodingUnavailableError(
                        "Сервис геокодирования вернул некорректный ответ"
                    )
                if not payload:
                    continue

                first_result = payload[0]
                try:
                    coordinates = Coordinates(
                        latitude=Decimal(str(first_result["lat"])),
                        longitude=Decimal(str(first_result["lon"])),
                    )
                except (InvalidOperation, KeyError, TypeError) as exc:
                    raise GeocodingUnavailableError(
                        "Сервис геокодирования вернул некорректный ответ"
                    ) from exc

                self._cache[normalized_address] = coordinates
                return coordinates

            raise AddressNotFoundError(normalized_address)
