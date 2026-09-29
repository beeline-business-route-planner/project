import json
import unittest
from decimal import Decimal
from unittest.mock import patch

import httpx
from src.config import cfg
from src.core.geocoding import (
    AddressNotFoundError,
    Coordinates,
    GeocodingClient,
    GeocodingService,
    GeocodingUnavailableError,
)


def _suggestion(qc_geo: str | None, lat: str | None = "55.6512", lon: str | None = "37.5971"):
    return {"value": "адрес", "data": {"geo_lat": lat, "geo_lon": lon, "qc_geo": qc_geo}}


class DadataGeocodingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        key = patch.object(cfg.geocoding, "api_key", "test-key")
        key.start()
        self.addCleanup(key.stop)
        self.queries: list[str] = []

    def _service(self, answers: list[dict] | Exception) -> GeocodingService:
        def handler(request: httpx.Request) -> httpx.Response:
            self.queries.append(json.loads(request.content)["query"])
            if isinstance(answers, Exception):
                raise answers
            return httpx.Response(200, json=answers[min(len(self.queries), len(answers)) - 1])

        session = httpx.AsyncClient(
            base_url="https://suggestions.test", transport=httpx.MockTransport(handler)
        )
        self.addAsyncCleanup(session.aclose)
        return GeocodingService(GeocodingClient(session))

    async def test_house_coordinates_are_returned_and_cached(self) -> None:
        service = self._service([{"suggestions": [_suggestion("0")]}])

        first = await service.geocode("Город Москва, б-р.Черноморский, д. 19 к 2")
        second = await service.geocode("Город  Москва, б-р.Черноморский, д. 19 к 2")

        self.assertEqual(first, Coordinates(Decimal("55.6512"), Decimal("37.5971")))
        self.assertEqual(second, first)
        self.assertEqual(self.queries, ["Город Москва, б-р.Черноморский, д. 19 к 2"])

    async def test_street_level_suggestion_tries_normalized_query(self) -> None:
        service = self._service(
            [{"suggestions": [_suggestion("2")]}, {"suggestions": [_suggestion("1")]}]
        )

        await service.geocode("Город Москва, б-р.Черноморский, д. 19 к 2")

        self.assertEqual(len(self.queries), 2)
        self.assertEqual(self.queries[1], "Москва, бульвар Черноморский, 19к2")

    async def test_precise_building_of_same_house_replaces_house_without_coordinates(self) -> None:
        requested = _suggestion("2", lat="55.1", lon="37.1")
        requested["data"].update(street_fias_id="street", house="1")
        other_street = _suggestion("0", lat="55.9", lon="37.9")
        other_street["data"].update(street_fias_id="other", house="1")
        building = _suggestion("0", lat="55.6", lon="37.6")
        building["data"].update(street_fias_id="street", house="1")
        service = self._service([{"suggestions": [requested, other_street, building]}])

        point = await service.geocode("г. Москва, ул Бирюлёвская, д 1с1")

        self.assertEqual(point, Coordinates(Decimal("55.6"), Decimal("37.6")))
        self.assertEqual(len(self.queries), 1)

    async def test_no_precise_coordinates_is_address_not_found(self) -> None:
        service = self._service([{"suggestions": [_suggestion("3")]}, {"suggestions": []}])

        with self.assertRaises(AddressNotFoundError):
            await service.geocode("Московская область, г. Кашира, ул. Ленина, д. 9")

    async def test_transport_error_and_missing_key_are_unavailable(self) -> None:
        service = self._service(httpx.ConnectError("down"))
        with self.assertRaises(GeocodingUnavailableError):
            await service.geocode("Москва, Сухонская, 11")

        with (
            patch.object(cfg.geocoding, "api_key", ""),
            self.assertRaises(GeocodingUnavailableError),
        ):
            await service.geocode("Москва, Сухонская, 11")
