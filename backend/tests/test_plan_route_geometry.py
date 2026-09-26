import json
import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from src.api.exc.plans import (
    PlanEngineerNotFoundError,
    PlanRouteCoordinatesMissingError,
    PlanRouteUnavailableError,
)
from src.api.plans.service import PlanRouteService
from src.config import cfg
from src.core.db.enums import VehicleType
from src.core.dgis.client import DgisClient
from src.core.dgis.exc import DgisUnavailableError, InvalidDgisResponseError
from src.core.dgis.route import DgisRouteService, RouteLeg


class DgisRouteGeometryTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_vehicle_types_use_matching_routing_api(self) -> None:
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append((request.url.path, json.loads(request.content)))
            if request.url.path == "/public_transport/2.0":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "total_distance": 510,
                            "total_duration": 190,
                            "movements": [
                                {
                                    "alternatives": [
                                        {
                                            "geometry": [
                                                {"selection": "LINESTRING(37.1 55.1, 37.15 55.15)"},
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "alternatives": [
                                        {
                                            "geometry": [
                                                {"selection": "LINESTRING(37.15 55.15, 37.2 55.2)"},
                                            ]
                                        }
                                    ]
                                },
                            ],
                        }
                    ],
                )
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "result": [
                        {
                            "total_distance": 510,
                            "total_duration": 190,
                            "maneuvers": [
                                {
                                    "outcoming_path": {
                                        "geometry": [
                                            {"selection": "LINESTRING(37.1 55.1 0, 37.15 55.15 0)"},
                                            {"selection": "LINESTRING(37.15 55.15, 37.2 55.2)"},
                                        ]
                                    }
                                },
                            ],
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(
            base_url="https://routing.example.invalid",
            transport=httpx.MockTransport(respond),
        ) as client:
            service = DgisRouteService(DgisClient(client))
            with patch.object(cfg.dgis, "api_key", "test-key"):
                for vehicle in VehicleType:
                    with self.subTest(vehicle=vehicle):
                        leg = await service.build_leg((37.1, 55.1), (37.2, 55.2), vehicle)
                        self.assertEqual(
                            leg.coordinates,
                            (
                                (37.1, 55.1),
                                (37.15, 55.15),
                                (37.2, 55.2),
                            ),
                        )
                        self.assertEqual(leg.distance_meters, 510)
        self.assertEqual(
            [item[0] for item in requests],
            [
                "/routing/7.0.0/global",
                "/routing/7.0.0/global",
                "/routing/7.0.0/global",
                "/public_transport/2.0",
            ],
        )
        self.assertEqual(
            [item[1].get("transport") for item in requests],
            [
                "driving",
                "walking",
                "bicycle",
                [
                    "metro",
                    "bus",
                    "tram",
                    "trolleybus",
                    "shuttle_bus",
                    "suburban_train",
                    "mcc",
                    "mcd",
                    "pedestrian",
                ],
            ],
        )

    def test_invalid_wkt_is_rejected(self) -> None:
        with self.assertRaises(InvalidDgisResponseError):
            DgisRouteService._parse_linestring("POINT(37.1 55.1)")


class PlanRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.plan_id = uuid.uuid4()
        self.engineer_id = uuid.uuid4()
        self.stops = [
            SimpleNamespace(latitude=Decimal("55.2"), longitude=Decimal("37.2")),
            SimpleNamespace(latitude=Decimal("55.3"), longitude=Decimal("37.3")),
        ]
        self.engineer = SimpleNamespace(
            engineer_id=self.engineer_id,
            start_latitude=Decimal("55.1"),
            start_longitude=Decimal("37.1"),
            vehicle_type=VehicleType.BICYCLE,
            stops=self.stops,
        )
        self.plans = SimpleNamespace(
            get_by_id=AsyncMock(return_value=SimpleNamespace(engineers=(self.engineer,)))
        )
        self.routes = SimpleNamespace(
            build_leg=AsyncMock(
                side_effect=[
                    RouteLeg(((37.1, 55.1), (37.15, 55.15), (37.2, 55.2)), 500, 180),
                    RouteLeg(((37.2, 55.2), (37.25, 55.25), (37.3, 55.3)), 600, 220),
                ]
            )
        )
        self.service = PlanRouteService(self.plans, self.routes)

    async def test_route_uses_saved_stop_order_and_joins_legs(self) -> None:
        result = await self.service.get_engineer_route(self.plan_id, self.engineer_id)
        self.assertEqual(result.profile, VehicleType.BICYCLE)
        self.assertEqual(len(result.geometry), 5)
        self.assertEqual((result.distance_meters, result.duration_seconds), (1100, 400))
        self.assertEqual(
            [(part.sequence, part.point_start, part.point_end) for part in result.segments],
            [(1, 0, 2), (2, 2, 4)],
        )
        self.assertEqual(
            self.routes.build_leg.await_args_list[0].args,
            ((37.1, 55.1), (37.2, 55.2), VehicleType.BICYCLE),
        )
        self.assertEqual(
            self.routes.build_leg.await_args_list[1].args,
            ((37.2, 55.2), (37.3, 55.3), VehicleType.BICYCLE),
        )

    async def test_no_foreign_engineer_and_no_missing_coordinate(self) -> None:
        with self.assertRaises(PlanEngineerNotFoundError):
            await self.service.get_engineer_route(self.plan_id, uuid.uuid4())
        self.stops[1].latitude = None
        with self.assertRaises(PlanRouteCoordinatesMissingError):
            await self.service.get_engineer_route(self.plan_id, self.engineer_id)
        self.routes.build_leg.assert_not_awaited()

    async def test_provider_failure_does_not_return_straight_line(self) -> None:
        self.routes.build_leg.side_effect = DgisUnavailableError("offline")
        with self.assertRaises(PlanRouteUnavailableError):
            await self.service.get_engineer_route(self.plan_id, self.engineer_id)


class RouteApiResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_response_keeps_coordinates_in_longitude_latitude_order(self) -> None:
        from src.api.plans.dto import EngineerRouteDTO, RouteSegmentDTO
        from src.api.plans.router import get_engineer_route

        plan_id = uuid.uuid4()
        engineer_id = uuid.uuid4()
        route = EngineerRouteDTO(
            engineer_id=engineer_id,
            profile=VehicleType.CAR,
            provider="2gis-routing",
            geometry=((37.1, 55.1), (37.2, 55.2)),
            distance_meters=1000,
            duration_seconds=200,
            segments=(RouteSegmentDTO(1, 1000, 200, 0, 1),),
        )
        service = SimpleNamespace(get_engineer_route=AsyncMock(return_value=route))
        response = await get_engineer_route(service, plan_id, engineer_id)
        self.assertEqual(response.geometry.coordinates, [(37.1, 55.1), (37.2, 55.2)])
        self.assertEqual(response.profile, VehicleType.CAR)
        self.assertEqual(response.segments[0].point_end, 1)
