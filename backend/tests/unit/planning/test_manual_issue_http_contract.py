"""Ошибки ручного маршрута сохраняют ID и причины заявок в HTTP-ответе."""

import unittest
import uuid

import httpx
from fastapi import FastAPI
from src.api.exc.base import register_all
from src.api.exc.planning import ManualRouteInvalid


class ManualIssueHttpContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_route_returns_issue_for_card(self) -> None:
        request_id = uuid.uuid4()
        app = FastAPI()

        @app.get("/invalid")
        async def invalid() -> None:
            raise ManualRouteInvalid(
                [
                    {
                        "request_id": str(request_id),
                        "engineer_id": None,
                        "code": "late",
                        "at": "2026-09-29T14:30:00",
                        "limit": "2026-09-29T14:00:00",
                    }
                ]
            )

        register_all(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test.local"
        ) as client:
            response = await client.get("/invalid")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["details"]["issues"][0]["request_id"], str(request_id))
        self.assertEqual(response.json()["details"]["issues"][0]["code"], "late")
