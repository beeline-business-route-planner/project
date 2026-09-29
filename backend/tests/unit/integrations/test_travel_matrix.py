import unittest
import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

import httpx
from src.config import cfg
from src.core.db.enums import VehicleType
from src.core.dgis import DgisUnavailableError
from src.core.routing import RoutingClient, RoutingPoint, RoutingService
from src.core.travel_matrix import (
    InvalidTravelMatrixResponseError,
    MatrixPoint,
    MatrixRequest,
    TravelMatrixService,
    TravelMatrixUnavailableError,
)


class OsrmMatricesTest(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_osrm_matrix_is_reported_as_provider_error(self) -> None:
        session = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"code": "Ok", "durations": [[0]], "distances": [[0]]},
                )
            )
        )
        self.addAsyncCleanup(session.aclose)
        points = [
            MatrixPoint(uuid.UUID(int=index), Decimal("55.7"), Decimal("37.6")) for index in (1, 2)
        ]
        request = MatrixRequest(
            VehicleType.CAR,
            datetime(2026, 9, 28, 11),
            frozenset({points[0].id}),
            frozenset({points[1].id}),
        )
        with (
            patch.object(cfg.travel_matrix, "provider", "osrm"),
            patch.object(cfg.routing, "car_table_url", "https://car.test/table"),
            self.assertRaises(InvalidTravelMatrixResponseError),
        ):
            await TravelMatrixService(Mock(), RoutingService(RoutingClient(session))).build(
                points, [request]
            )

    async def test_each_profile_is_requested_once_and_public_transport_is_derived(self) -> None:
        seconds = {"car": 600, "foot": 3000, "bike": 1200}
        meters = {"car": 10_000, "foot": 3_000, "bike": 9_000}
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            profile = request.url.host.split(".")[0]
            return httpx.Response(
                200,
                json={
                    "code": "Ok",
                    "durations": [[0, seconds[profile]], [seconds[profile], 0]],
                    "distances": [[0, meters[profile]], [meters[profile], 0]],
                },
            )

        session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(session.aclose)
        points = [
            MatrixPoint(uuid.UUID(int=index), Decimal("55.7"), Decimal("37.6")) for index in (1, 2)
        ]
        with (
            patch.object(cfg.routing, "car_table_url", "https://car.test/table"),
            patch.object(cfg.routing, "foot_table_url", "https://foot.test/table"),
            patch.object(cfg.routing, "bike_table_url", "https://bike.test/table"),
            patch.object(cfg.routing, "travel_buffer_multiplier", 1.0),
            patch.object(cfg.routing, "public_transport_speed_kmh", 20.0),
            patch.object(cfg.routing, "public_transport_wait_minutes", 10),
        ):
            matrices = await RoutingService(RoutingClient(session)).build_matrices(
                [RoutingPoint(point.id, point.latitude, point.longitude) for point in points],
                set(VehicleType),
            )

        self.assertEqual(
            sorted(url.split("/")[2] for url in urls), ["bike.test", "car.test", "foot.test"]
        )
        first, second = points[0].id, points[1].id
        self.assertEqual(matrices[VehicleType.CAR].minutes(first, second), 10)
        self.assertEqual(matrices[VehicleType.PEDESTRIAN].minutes(first, second), 50)
        self.assertEqual(matrices[VehicleType.BICYCLE].minutes(first, second), 20)
        # 10 км со скоростью 20 км/ч = 30 минут + 10 ожидания = 40 < 50 пешком.
        self.assertEqual(matrices[VehicleType.PUBLIC_TRANSPORT].minutes(first, second), 40)
        self.assertEqual(
            matrices[VehicleType.PUBLIC_TRANSPORT].kilometers(first, second), Decimal("10")
        )


class TravelMatrixProviderTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.points = [MatrixPoint(uuid.UUID(int=1), Decimal("55.7"), Decimal("37.6"))]
        self.requests = [
            MatrixRequest(VehicleType.CAR, datetime(2026, 9, 27, 11), frozenset(), frozenset()),
            MatrixRequest(VehicleType.CAR, datetime(2026, 9, 27, 13), frozenset(), frozenset()),
        ]
        self.dgis = Mock(build_matrix=AsyncMock(return_value="dgis-matrix"))
        self.osrm = Mock(build_matrices=AsyncMock(return_value={VehicleType.CAR: "osrm-matrix"}))
        self.service = TravelMatrixService(self.dgis, self.osrm)

    async def test_osrm_builds_one_matrix_per_vehicle(self) -> None:
        with patch.object(cfg.travel_matrix, "provider", "osrm"):
            matrices = await self.service.build(self.points, self.requests)

        self.assertEqual(matrices, ["osrm-matrix", "osrm-matrix"])
        self.osrm.build_matrices.assert_awaited_once()
        self.dgis.build_matrix.assert_not_awaited()

    async def test_dgis_builds_matrix_per_request_and_errors_are_translated(self) -> None:
        with patch.object(cfg.travel_matrix, "provider", "dgis"):
            matrices = await self.service.build(self.points, self.requests)
            self.assertEqual(matrices, ["dgis-matrix", "dgis-matrix"])
            self.assertEqual(self.dgis.build_matrix.await_count, 2)

            self.dgis.build_matrix.side_effect = DgisUnavailableError("limit")
            with self.assertRaises(TravelMatrixUnavailableError):
                await self.service.build(self.points, self.requests)
