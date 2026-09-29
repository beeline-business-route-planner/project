import asyncio
import re
from decimal import Decimal, InvalidOperation

import httpx

from src.config import cfg
from src.core.geocoding.client import GeocodingClient
from src.core.geocoding.dto import Coordinates
from src.core.geocoding.exc import AddressNotFoundError, GeocodingUnavailableError
from src.core.geocoding.normalizer import RussianAddressNormalizer


class GeocodingService:
    """Геокодирует адреса через подсказки DaData с кэшем и ограничением параллельности."""

    def __init__(self, client: GeocodingClient) -> None:
        self._client = client
        self._cache: dict[str, Coordinates] = {}
        self._requests = asyncio.Semaphore(cfg.geocoding.max_concurrent_requests)

    async def geocode(self, address: str) -> Coordinates:
        """Возвращает координаты дома; координаты грубее `max_qc_geo` не принимаются.

        Сначала запрашивается исходная строка, затем варианты нормализатора: подсказка
        по исходной строке может оказаться улицей, а не домом.

        Raises:
            AddressNotFoundError: если ни один вариант не дал координаты нужной точности.
            GeocodingUnavailableError: если не задан ключ или DaData недоступна.
        """

        if not cfg.geocoding.api_key:
            raise GeocodingUnavailableError("Не задан geocoding.api_key")
        normalized_address = " ".join(address.split())
        cached = self._cache.get(normalized_address)
        if cached is not None:
            return cached

        queries = (normalized_address, *RussianAddressNormalizer.queries(normalized_address))
        for query in dict.fromkeys(queries):
            coordinates = await self._suggest(query)
            if coordinates is not None:
                self._cache[normalized_address] = coordinates
                return coordinates
        raise AddressNotFoundError(normalized_address)

    async def _suggest(self, query: str) -> Coordinates | None:
        async with self._requests:
            try:
                response = await self._client.get().post(
                    "/suggestions/api/4_1/rs/suggest/address",
                    json={"query": query, "count": cfg.geocoding.suggestions_count},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise GeocodingUnavailableError("Сервис геокодирования недоступен") from exc

        suggestions = payload.get("suggestions") if isinstance(payload, dict) else None
        if not isinstance(suggestions, list) or not all(
            isinstance(item, dict) and isinstance(item.get("data"), dict) for item in suggestions
        ):
            raise GeocodingUnavailableError("Сервис геокодирования вернул некорректный ответ")
        if not suggestions:
            return None
        found = [item["data"] for item in suggestions]
        best = found[0]
        if not self._is_precise(best):
            best = next(
                (data for data in found[1:] if self._same_house(found[0], data)),
                best,
            )
        if not self._is_precise(best):
            return None
        try:
            return Coordinates(
                latitude=Decimal(str(best["geo_lat"])),
                longitude=Decimal(str(best["geo_lon"])),
            )
        except (InvalidOperation, KeyError, TypeError) as exc:
            raise GeocodingUnavailableError(
                "Сервис геокодирования вернул некорректный ответ"
            ) from exc

    @staticmethod
    def _is_precise(data: dict[str, object]) -> bool:
        qc_geo = data.get("qc_geo")
        return (
            data.get("geo_lat") is not None
            and data.get("geo_lon") is not None
            and isinstance(qc_geo, str | int)
            and str(qc_geo).isdigit()
            and int(qc_geo) <= cfg.geocoding.max_qc_geo
        )

    @staticmethod
    def _same_house(requested: dict[str, object], candidate: dict[str, object]) -> bool:
        """Строение того же дома: у дома из справочника часто нет координат, у его корпусов есть.

        Совпадать должны улица по ФИАС и номер дома без корпуса/строения/литеры.
        """

        street = requested.get("street_fias_id")
        requested_house = re.match(r"\d+", str(requested.get("house") or ""))
        candidate_house = re.match(r"\d+", str(candidate.get("house") or ""))
        return (
            street is not None
            and street == candidate.get("street_fias_id")
            and requested_house is not None
            and candidate_house is not None
            and requested_house.group() == candidate_house.group()
            and GeocodingService._is_precise(candidate)
        )
