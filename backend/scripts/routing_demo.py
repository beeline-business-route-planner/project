#!/usr/bin/env python3
"""Create an explicitly synthetic, geocoded demo in a disposable development database."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import statistics
import time
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID

import httpx
from openpyxl import Workbook
from redis.asyncio import Redis
from sqlalchemy import select

from beeline_backend.config import Settings
from beeline_backend.infrastructure.db import create_engine, create_session_factory
from beeline_backend.infrastructure.gateway import _normalize_address
from beeline_backend.infrastructure.models import LocationRow, PlanningRunRow

POINTS = [
    (37.6173, 55.7558),
    (37.601, 55.752),
    (37.631, 55.765),
    (37.640, 55.753),
    (37.605, 55.768),
    (37.655, 55.770),
    (37.590, 55.745),
    (37.630, 55.743),
    (37.650, 55.746),
    (37.620, 55.780),
]


def workbook(planning_date: date, addresses: list[str]) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Лист 1 - Восток Синтетические д"
    sheet.append(["Восток Синтетические данные"])
    sheet.append(
        [
            "Заявка",
            "Тип заявки BK",
            "Тип заявки HD",
            "Начало",
            "Окончание",
            "Район",
            "Адрес",
            "Подключение",
            "Гигабитное подключение",
        ]
    )
    for index, address in enumerate(addresses[1:9], 1):
        sheet.append(
            [
                index,
                "Локальная заявка",
                "Нет линка",
                f"{planning_date:%d.%m.%Y} 08:00",
                f"{planning_date:%d.%m.%Y} 23:00",
                "Центр",
                address,
                None,
                "Нет",
            ]
        )
    sheet.append([None])
    sheet.append(["Адрес Офиса", addresses[0]])
    output = BytesIO()
    book.save(output)
    return output.getvalue()


async def main(args: argparse.Namespace) -> None:
    engine = create_engine(Settings(database_url=args.database_url))
    factory = create_session_factory(engine)
    cache = Redis.from_url(args.dragonfly_url, decode_responses=True)
    planning_date = date.fromisoformat(args.date) if args.date else date.today() + timedelta(days=1)
    addresses = [f"Москва, контрольная точка routing demo {i}" for i in range(len(POINTS))]
    try:
        async with httpx.AsyncClient(base_url=args.api_url, timeout=60, trust_env=False) as client:
            existing = await client.get("/api/v1/scenarios")
            existing.raise_for_status()
            used_dates = {day for scenario in existing.json() for day in scenario["planning_dates"]}
            if args.date and str(planning_date) in used_dates:
                raise ValueError(
                    "This demo date already exists; choose an unused date or omit --date"
                )
            while str(planning_date) in used_dates:
                planning_date += timedelta(days=1)
            snapped = []
            for lon, lat in POINTS:
                response = await client.get(f"{args.osrm_url}/nearest/v1/driving/{lon},{lat}")
                response.raise_for_status()
                snapped.append(response.json()["waypoints"][0]["location"])
            async with factory() as session, session.begin():
                for address, (lon, lat) in zip(addresses, snapped, strict=True):
                    existing = await session.scalar(
                        select(LocationRow).where(
                            LocationRow.normalized_address == _normalize_address(address),
                            LocationRow.region == "Москва",
                        )
                    )
                    if existing is None:
                        session.add(
                            LocationRow(
                                address=address,
                                normalized_address=_normalize_address(address),
                                region="Москва",
                                longitude=lon,
                                latitude=lat,
                                coordinate_source="routing_demo_osrm_nearest",
                                coordinate_version=1,
                                created_at=datetime.now(UTC),
                            )
                        )

            async def request(method: str, path: str, **kwargs):
                response = await client.request(method, path, **kwargs)
                if response.status_code != 200:
                    raise RuntimeError(
                        f"{method} {path}: {response.status_code}: {response.text[:1000]}"
                    )
                return response

            imported = (
                await request(
                    "POST",
                    "/api/v1/imports",
                    files={
                        "file": (
                            "Восток Синтетические данные.xlsx",
                            workbook(planning_date, addresses),
                        )
                    },
                )
            ).json()
            plan_input = {
                "scenario_id": imported["scenario_id"],
                "planning_date": str(planning_date),
                "as_of": f"{planning_date}T08:00:00+03:00",
            }
            first_run = (await request("POST", "/api/v1/plans/run", json=plan_input)).json()
            plan_id = first_run["plan_id"]
            overview_response = await request("GET", f"/api/v1/plans/{plan_id}/routes")
            overview = overview_response.json()
            details = [
                (
                    await request(
                        "GET", f"/api/v1/plans/{plan_id}/engineers/{route['engineer_id']}/route"
                    )
                ).json()
                for route in overview["routes"]
            ]
            detailed_equivalent = [
                {key: detail[key] for key in overview["routes"][0]} for detail in details
            ]

            def compact(obj):
                return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode())

            overview_bytes, detailed_bytes = (
                compact(overview["routes"]),
                compact(detailed_equivalent),
            )
            read_url = f"/api/v1/plans/{plan_id}/routes"
            samples = {"cold": [], "warm": []}
            for mode in samples:
                for _ in range(args.repeats):
                    if mode == "cold":
                        keys = [
                            key
                            async for key in cache.scan_iter(match=f"routes:v1:plan:{plan_id}:*")
                        ]
                        if keys:
                            await cache.delete(*keys)
                    start = time.perf_counter()
                    await request("GET", read_url)
                    samples[mode].append((time.perf_counter() - start) * 1000)
            await request(
                "POST",
                f"/api/v1/plans/{plan_id}/approve",
                json={"expected_base_plan_id": None, "actor": "routing-demo"},
            )
            second_run = (
                await request(
                    "POST", "/api/v1/plans/run", json={**plan_input, "base_plan_id": plan_id}
                )
            ).json()
            urgent = (
                await request(
                    "POST",
                    "/api/v1/requests",
                    json={
                        "scenario_id": imported["scenario_id"],
                        "planning_date": str(planning_date),
                        "external_id": "routing-demo-urgent",
                        "address": addresses[-1],
                        "district": "Центр",
                        "window_start": f"{planning_date}T08:00:00+03:00",
                        "window_end": f"{planning_date}T23:00:00+03:00",
                        "service_minutes": 30,
                        "required_skill": "local",
                        "priority": "urgent",
                        "idempotency_key": f"routing-demo-urgent:{planning_date}",
                        "actor": "routing-demo",
                    },
                )
            ).json()
            unchanged_old = (await request("GET", read_url)).json()
            assert unchanged_old["routes"] == overview["routes"]
            runs = [first_run, second_run]
            if urgent.get("replanning"):
                runs.append(urgent["replanning"])
            diagnostics = []
            async with factory() as session:
                for run in runs:
                    row = await session.get(PlanningRunRow, UUID(run["planning_run_id"]))
                    diagnostics.append({"plan_id": run["plan_id"], **row.diagnostics})
            latencies = {
                mode: {
                    "p50_ms": round(statistics.median(values), 3),
                    "p95_ms": round(sorted(values)[math.ceil(len(values) * 0.95) - 1], 3),
                }
                for mode, values in samples.items()
            }
            result = {
                "recorded_at": datetime.now(UTC).isoformat(),
                "fixture": "8 synthetic requests, known Moscow road coordinates; no address geocoding",
                "platform": platform.platform(),
                "planning_date": str(planning_date),
                "scenario_id": imported["scenario_id"],
                "plan_id": plan_id,
                "engineer_id": next(
                    route["engineer_id"]
                    for route in overview["routes"]
                    if route["route_status"] == "ready"
                ),
                "engineers": len(overview["routes"]),
                "repeats": args.repeats,
                "concurrency": 1,
                "detailed_coordinates": sum(
                    len(d["geometry"]["coordinates"]) for d in details if d["geometry"]
                ),
                "overview_coordinates": sum(
                    len(r["geometry"]["coordinates"]) for r in overview["routes"] if r["geometry"]
                ),
                "detailed_comparable_json_bytes": detailed_bytes,
                "overview_comparable_json_bytes": overview_bytes,
                "payload_reduction_percent": round(100 * (1 - overview_bytes / detailed_bytes), 2),
                "actual_overview_response_bytes": len(overview_response.content),
                "latency": latencies,
                "routing_runs": diagnostics,
                "old_plan_geometry_preserved": True,
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await cache.aclose()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", required=True, help="Disposable development DB, never production"
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--osrm-url", default="http://127.0.0.1:5000")
    parser.add_argument("--dragonfly-url", default="redis://127.0.0.1:56379/0")
    parser.add_argument("--date")
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("routing-demo-results.json"))
    arguments = parser.parse_args()
    if arguments.repeats < 2:
        parser.error("--repeats must be at least 2")
    asyncio.run(main(arguments))
