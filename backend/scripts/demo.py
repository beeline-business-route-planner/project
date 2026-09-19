"""Run the complete backend demo flow against a running API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx


def with_business_timezone(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Moscow"))
    return parsed.isoformat()


async def main(api_url: str, dataset: Path) -> None:
    content = dataset.read_bytes()
    demo_key = hashlib.sha256(content).hexdigest()[:16]

    async with httpx.AsyncClient(base_url=api_url.rstrip("/"), timeout=120) as client:
        async def request(method: str, path: str, **kwargs: object) -> httpx.Response:
            response = await client.request(method, path, **kwargs)
            if response.is_error:
                correlation_id = response.headers.get("X-Correlation-ID", "unknown")
                raise RuntimeError(
                    f"{method} {path} failed with {response.status_code}; "
                    f"correlation_id={correlation_id}; body={response.text[:1000]}"
                )
            return response

        imported = (
            await request(
                "POST",
                "/api/v1/imports",
                headers={"Idempotency-Key": f"demo-import:{demo_key}"},
                files={
                    "file": (
                        dataset.name,
                        content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        ).json()
        scenario_id = imported["scenario_id"]
        scenarios = (await request("GET", "/api/v1/scenarios")).json()
        scenario = next(item for item in scenarios if item["id"] == scenario_id)
        planning_date = scenario["planning_dates"][0]
        plan_payload = {
            "scenario_id": scenario_id,
            "planning_date": planning_date,
            "as_of": f"{planning_date}T08:00:00+03:00",
        }

        initial = (
            await request(
                "POST",
                "/api/v1/plans/run",
                headers={"Idempotency-Key": f"demo-plan:{demo_key}"},
                json=plan_payload,
            )
        ).json()
        initial_plan_id = initial["plan_id"]
        await request(
            "POST",
            f"/api/v1/plans/{initial_plan_id}/approve",
            json={"expected_base_plan_id": None, "actor": "demo-script"},
        )
        overview = (
            await request("GET", f"/api/v1/plans/{initial_plan_id}/routes")
        ).json()
        ready_route = next(
            (route for route in overview["routes"] if route["route_status"] == "ready"),
            None,
        )
        detailed = None
        if ready_route is not None:
            detailed = (
                await request(
                    "GET",
                    f"/api/v1/plans/{initial_plan_id}/engineers/"
                    f"{ready_route['engineer_id']}/route",
                )
            ).json()

        requests = (
            await request(
                "GET",
                "/api/v1/requests",
                params={"scenario_id": scenario_id, "planning_date": planning_date},
            )
        ).json()
        source = requests[0]
        urgent = (
            await request(
                "POST",
                "/api/v1/requests",
                json={
                    "scenario_id": scenario_id,
                    "planning_date": planning_date,
                    "external_id": f"demo-urgent-{demo_key}",
                    "address": source["address"],
                    "district": "Demo",
                    "window_start": with_business_timezone(source["window_start"]),
                    "window_end": with_business_timezone(source["window_end"]),
                    "service_minutes": 30,
                    "required_skill": "local",
                    "required_transport": "car",
                    "priority": "urgent",
                    "idempotency_key": f"demo-urgent:{demo_key}",
                    "actor": "demo-script",
                },
            )
        ).json()
        replanned = (
            await request(
                "POST",
                "/api/v1/plans/replan",
                headers={"Idempotency-Key": f"demo-replan:{demo_key}"},
                json={**plan_payload, "base_plan_id": initial_plan_id},
            )
        ).json()
        new_plan_id = replanned["plan_id"]
        changes = (
            await request("GET", f"/api/v1/plans/{new_plan_id}/changes")
        ).json()
        new_overview = (
            await request("GET", f"/api/v1/plans/{new_plan_id}/routes")
        ).json()

        print(
            json.dumps(
                {
                    "scenario_id": scenario_id,
                    "planning_date": planning_date,
                    "initial_plan_id": initial_plan_id,
                    "initial_plan_status": "approved",
                    "urgent_request_id": urgent["request_id"],
                    "new_plan_id": new_plan_id,
                    "changes": changes["changes"],
                    "overview_routes": len(new_overview["routes"]),
                    "detailed_route_checked": detailed is not None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Synthetic XLSX dataset")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.api_url, arguments.dataset))
