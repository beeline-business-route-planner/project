from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from beeline_backend.application.planner import DeterministicPlanningAlgorithm
from beeline_backend.application.routing import RouteBuilder
from beeline_backend.application.services import BackendService
from beeline_backend.config import get_settings
from beeline_backend.infrastructure.clock import SystemClock
from beeline_backend.infrastructure.db import create_engine, create_session_factory
from beeline_backend.infrastructure.gateway import SqlGateway
from beeline_backend.infrastructure.importer import XlsxDatasetImporter
from beeline_backend.infrastructure.providers import DemoGeocoder, DemoRoutingProvider
from beeline_backend.infrastructure.route_store import SqlSegmentStore


async def _seed_demo(dataset_path: Path) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    clock = SystemClock()
    async with factory() as session:
        gateway = SqlGateway(session, clock, DemoGeocoder(), settings.business_timezone)
        service = BackendService(
            gateway,
            XlsxDatasetImporter(settings.business_timezone),
            DemoRoutingProvider(clock),
            DeterministicPlanningAlgorithm(),
            clock,
            RouteBuilder(DemoRoutingProvider(clock), SqlSegmentStore(factory), settings.route_overview_tolerance_meters, settings.osrm_max_concurrency),
        )
        result = await service.import_dataset(
            dataset_path.name,
            dataset_path.read_bytes(),
            f"seed:{dataset_path.name}",
        )
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    await engine.dispose()


async def _plan_demo(scenario_id: UUID, planning_date: date) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    clock = SystemClock()
    async with factory() as session:
        gateway = SqlGateway(session, clock, DemoGeocoder(), settings.business_timezone)
        service = BackendService(
            gateway,
            XlsxDatasetImporter(settings.business_timezone),
            DemoRoutingProvider(clock),
            DeterministicPlanningAlgorithm(),
            clock,
            RouteBuilder(DemoRoutingProvider(clock), SqlSegmentStore(factory), settings.route_overview_tolerance_meters, settings.osrm_max_concurrency),
        )
        result = await service.run_plan(
            scenario_id,
            planning_date,
            None,
            datetime.combine(planning_date, datetime.min.time(), ZoneInfo(settings.business_timezone)),
        )
        plan = await gateway.get_plan(UUID(str(result["plan_id"])))
        assignments = cast(list[object], plan["assignments"])
        unassigned = cast(list[object], plan["unassigned"])
        print(
            json.dumps(
                {
                    **result,
                    "assigned": len(assignments),
                    "unassigned": len(unassigned),
                    "metrics": plan["metrics"],
                },
                ensure_ascii=False,
                default=str,
                indent=2,
            )
        )
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Beeline backend utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed = subparsers.add_parser("seed-demo", help="Import one supported synthetic workbook")
    seed.add_argument("dataset", type=Path)
    plan = subparsers.add_parser("plan-demo", help="Run the deterministic planning adapter")
    plan.add_argument("scenario_id", type=UUID)
    plan.add_argument("planning_date", type=date.fromisoformat)
    args = parser.parse_args()
    if args.command == "seed-demo":
        asyncio.run(_seed_demo(args.dataset))
    elif args.command == "plan-demo":
        asyncio.run(_plan_demo(args.scenario_id, args.planning_date))


if __name__ == "__main__":
    main()
