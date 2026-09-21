import asyncio
import re
from decimal import Decimal, InvalidOperation
from time import monotonic

import httpx

from src.config import cfg
from src.core.geocoding.client import GeocodingClient
from src.core.geocoding.dto import Coordinates


class AddressNotFoundError(Exception):
    def __init__(self, address: str) -> None:
        self.address = address
        super().__init__(f"Координаты адреса не найдены: {address}")


class GeocodingUnavailableError(Exception):
    pass


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

            search_address = self._normalize_russian_address(normalized_address)
            simplified_address = re.sub(
                r"^(?:Московская область,\s*)?(?:г\.)?([^,]+),\s*"
                r"(?:посёлок|поселок|пгт)\s+[^,]+,\s*",
                r"\1, ",
                search_address,
            )
            queries = dict.fromkeys((search_address, simplified_address, normalized_address))
            for query in queries:
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

    def _normalize_russian_address(self, address: str) -> str:
        value = address
        value = re.sub(r"^(?:г\.\s*)?(?:Город\s+)?Москва,?\s*", "Москва, ", value)
        value = re.sub(r"^МО,\s*г\.\s*", "Московская область, ", value)
        value = value.replace("обл.Московская область", "Московская область")
        value = value.replace("пгт.", "посёлок ")

        remote_street = re.match(
            r"^(Московская область,\s*)?(Кашира|Ступино)\s+(.+?)\s+ул\.\s+д\.\s+(.+)$",
            value,
        )
        if remote_street is not None:
            region = remote_street.group(1) or ""
            value = (
                f"{region}{remote_street.group(2)}, улица {remote_street.group(3)}, "
                f"{remote_street.group(4)}"
            )

        moscow_street = re.match(r"^Москва,?\s+(.+?)\s+ул\.\s+д\.\s+(.+)$", value)
        if moscow_street is not None:
            value = f"Москва, улица {moscow_street.group(1)}, {moscow_street.group(2)}"
        moscow_passage = re.match(r"^Москва,?\s+(.+?)\s+пр-зд\.\s+д\.\s+(.+)$", value)
        if moscow_passage is not None:
            value = f"Москва, {moscow_passage.group(1)} проезд, {moscow_passage.group(2)}"

        replacements = {
            "пр-кт.": "проспект ",
            "ул.": "улица ",
            "пер.": "переулок ",
            "наб.": "набережная ",
            "б-р.": "бульвар ",
            "ш.": "шоссе ",
        }
        for source, replacement in replacements.items():
            value = value.replace(source, replacement)
        value = re.sub(r"(?<=,\s)ул\s+", "улица ", value)
        value = re.sub(
            r"(?<=,\s)проезд\.?\s*([^,]+)",
            lambda match: f"{match.group(1).strip()} проезд",
            value,
        )
        value = re.sub(
            r"([А-ЯЁ][а-яё-]+)\s+(\d+-[йя])\s+проезд",
            r"\2 \1 проезд",
            value,
        )
        value = re.sub(r",\s*д\.?\s*", ", ", value)
        value = re.sub(r"\s+к\s+(\d+)", r"к\1", value)
        value = re.sub(r"с\s+(\d+)", r"с\1", value)
        value = re.sub(r"\s*,\s*", ", ", value)
        return " ".join(value.split())
