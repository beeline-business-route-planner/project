import unittest
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
from src.config import cfg
from src.core.db.enums import VehicleType
from src.core.dgis import DgisClient, DgisMatrixService, DgisPoint, DgisUnavailableError


class DgisMatrixServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        for name, value in (
            ("api_key", "test-key"),
            ("rate_limit_retries", 2),
            ("max_matrix_sources", 2),
            ("max_matrix_targets", 2),
        ):
            patcher = patch.object(cfg.dgis, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        sleep = patch("src.core.dgis.service.asyncio.sleep", new_callable=AsyncMock)
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        self.points = [
            DgisPoint(id=uuid.UUID(int=index), latitude=Decimal("55.7"), longitude=Decimal("37.6"))
            for index in range(1, 4)
        ]

    def _service(self, responses: list[httpx.Response]) -> tuple[DgisMatrixService, list]:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return responses[min(len(requests), len(responses)) - 1]

        session = httpx.AsyncClient(base_url="https://dgis.test", transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(session.aclose)
        return DgisMatrixService(DgisClient(session)), requests

    async def test_rate_limit_is_retried_and_non_ok_status_is_unreachable(self) -> None:
        routes = [
            {"source_id": 0, "target_id": 1, "status": "OK", "duration": 600, "distance": 5000},
            {"source_id": 0, "target_id": 2, "status": "PLATFORMS_NOT_FOUND", "duration": 0,
             "distance": 0},
        ]
        service, requests = self._service(
            [httpx.Response(429, json={}), httpx.Response(200, json={"routes": routes})]
        )

        matrix = await service.build_matrix(
            self.points,
            VehicleType.PUBLIC_TRANSPORT,
            source_ids=frozenset({self.points[0].id}),
            target_ids=frozenset({self.points[1].id, self.points[2].id}),
        )

        self.assertEqual(len(requests), 2)
        self.sleep.assert_awaited_once()
        self.assertEqual(matrix.minutes(self.points[0].id, self.points[1].id), 10)
        self.assertIsNone(matrix.minutes(self.points[0].id, self.points[2].id))
        self.assertIn(b"public_transport_params", requests[-1].content)

    async def test_exhausted_rate_limit_is_unavailable(self) -> None:
        service, requests = self._service([httpx.Response(429, json={})])

        with self.assertRaises(DgisUnavailableError):
            await service.build_matrix(
                self.points,
                VehicleType.CAR,
                source_ids=frozenset({self.points[0].id}),
                target_ids=frozenset({self.points[1].id}),
            )
        self.assertEqual(len(requests), 3)

    def test_blocks_respect_source_and_target_limits(self) -> None:
        blocks = DgisMatrixService._matrix_blocks([0, 1, 2], [3, 4, 5])

        self.assertEqual(len(blocks), 4)
        self.assertTrue(all(len(sources) <= 2 and len(targets) <= 2 for sources, targets in blocks))
        pairs = {(s, t) for sources, targets in blocks for s in sources for t in targets}
        self.assertEqual(pairs, {(s, t) for s in (0, 1, 2) for t in (3, 4, 5)})
