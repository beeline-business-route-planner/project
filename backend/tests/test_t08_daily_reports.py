"""T08 report snapshots against a fresh disposable t08_test_* PostgreSQL database."""

import os
import unittest
import uuid
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from src.api.plans.snapshot import PlanSnapshotAssembler
from src.api.reports.pdf import DailyPdfRenderer
from src.api.reports.service import DailyReportService
from src.core.db.enums import (
    ApprovalStatus,
    DistributionMode,
    PlanKind,
    PlanStrategy,
    Region,
    ReplanningEventType,
    RequestTypeBk,
    RequestTypeHd,
    Skill,
    UnassignedReason,
    VehicleType,
)
from src.core.db.models import (
    BaselineResult,
    DataUpload,
    Engineer,
    Plan,
    PlanEngineerState,
    PlanStop,
    PlanUnassignedRequest,
    ReplanningEvent,
    Request,
)
from src.core.db.uow import UnitOfWork

DATABASE_URL = os.environ.get("T08_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "T08_TEST_DATABASE_URL is not set")
class DailyReportEndToEndTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        assert DATABASE_URL is not None
        url = make_url(DATABASE_URL)
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host not in {"127.0.0.1", "localhost", "postgres"}
            or not (url.database or "").startswith("t08_test_")
        ):
            self.fail("T08 requires a disposable local t08_test_* database")
        self.engine = create_async_engine(
            DATABASE_URL, connect_args={"server_settings": {"timezone": "UTC"}}
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as session:
            if await session.scalar(select(func.count()).select_from(Plan)):
                self.fail("T08 database must be freshly migrated and empty")

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_approved_only_latest_routes_and_summary(self) -> None:
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        morning = datetime.combine(today, time(9))
        early = (
            (morning + timedelta(minutes=30))
            .replace(tzinfo=ZoneInfo("Europe/Moscow"))
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        late = early + timedelta(hours=1)
        generated_at = datetime.combine(today, time(12), tzinfo=ZoneInfo("Europe/Moscow"))
        async with self.sessions() as session:
            for region in (Region.VOSTOK, Region.YUGO_VOSTOK):
                upload = DataUpload(id=uuid.uuid7(), region=region)
                engineer = Engineer(
                    id=uuid.uuid7(),
                    upload_id=upload.id,
                    name=f"Инженер {region.value}",
                    region=region,
                    start_point_address="Офис",
                    shift_start=morning,
                    shift_end=morning + timedelta(hours=8),
                    vehicle_type=VehicleType.CAR,
                    is_available=True,
                )
                request = Request(
                    id=uuid.uuid7(),
                    upload_id=upload.id,
                    external_id=100 if region == Region.VOSTOK else 200,
                    type_bk=RequestTypeBk.LOCAL_REQUEST,
                    type_hd=RequestTypeHd.INFORMATION,
                    region=region,
                    district="Район",
                    address="Адрес",
                    is_gigabit=False,
                    window_start=morning,
                    window_end=morning + timedelta(hours=8),
                    norm_minutes=50,
                    norm_minutes_without_travel=30,
                    priority=3,
                    required_skill=Skill.LOCAL_WORKS,
                )
                initial = Plan(
                    id=uuid.uuid7(),
                    region=region,
                    planning_date=today,
                    upload_id=upload.id,
                    kind=PlanKind.INITIAL,
                    mode=DistributionMode.MIN_ENGINEERS,
                    strategy=PlanStrategy.LAYERED_GRAPH,
                    approval_status=ApprovalStatus.APPROVED,
                    approved_at=early,
                    calculation_cutoff_at=morning,
                    assigned_requests_count=1,
                    unassigned_requests_count=1 if region == Region.YUGO_VOSTOK else 0,
                    engineers_used_count=1,
                    total_mileage_km=Decimal("1.00"),
                )
                session.add(upload)
                await session.flush()
                session.add_all([engineer, request])
                await session.flush()
                session.add(initial)
                await session.flush()
                session.add(
                    BaselineResult(
                        initial_plan_id=initial.id,
                        assigned_requests_count=1,
                        unassigned_requests_count=1 if region == Region.YUGO_VOSTOK else 0,
                        engineers_used_count=1,
                        total_mileage_km=Decimal("2.00"),
                        average_workload_with_travel=Decimal("10.42"),
                        average_workload_without_travel=Decimal("6.25"),
                        algorithm_version="test",
                    )
                )
                self._stop(session, initial.id, engineer.id, request.id, 1, morning)
                session.add(
                    PlanEngineerState(
                        plan_id=initial.id, engineer_id=engineer.id, is_available=True
                    )
                )
                if region == Region.YUGO_VOSTOK:
                    idle_engineer = Engineer(
                        id=uuid.uuid7(),
                        upload_id=upload.id,
                        name="Инженер без маршрута",
                        region=region,
                        start_point_address="Офис",
                        shift_start=morning,
                        shift_end=morning + timedelta(hours=8),
                        vehicle_type=VehicleType.CAR,
                        is_available=True,
                    )
                    session.add(idle_engineer)
                    await session.flush()
                    session.add(
                        PlanEngineerState(
                            plan_id=initial.id,
                            engineer_id=idle_engineer.id,
                            is_available=True,
                        )
                    )
                    extra = Request(
                        id=uuid.uuid7(),
                        upload_id=upload.id,
                        external_id=201,
                        type_bk=RequestTypeBk.LOCAL_REQUEST,
                        type_hd=RequestTypeHd.INFORMATION,
                        region=region,
                        district="Район",
                        address="Неназначенный адрес",
                        is_gigabit=False,
                        window_start=morning,
                        window_end=morning + timedelta(hours=8),
                        norm_minutes=50,
                        norm_minutes_without_travel=30,
                        priority=3,
                        required_skill=Skill.LOCAL_WORKS,
                    )
                    session.add(extra)
                    await session.flush()
                    session.add(
                        PlanUnassignedRequest(
                            plan_id=initial.id,
                            request_id=extra.id,
                            reason=UnassignedReason.NO_TIME_SLOT,
                        )
                    )
                if region == Region.VOSTOK:
                    urgent = Request(
                        id=uuid.uuid7(),
                        upload_id=None,
                        external_id=101,
                        type_bk=RequestTypeBk.GLOBAL_PROBLEM,
                        type_hd=RequestTypeHd.EMERGENCY,
                        region=region,
                        district="Район",
                        address="Срочный адрес",
                        is_gigabit=False,
                        window_start=morning,
                        window_end=morning + timedelta(hours=8),
                        norm_minutes=100,
                        norm_minutes_without_travel=80,
                        priority=1,
                        required_skill=Skill.EMERGENCY_WORKS,
                    )
                    approved_event = ReplanningEvent(
                        id=uuid.uuid7(),
                        region=region,
                        planning_date=today,
                        event_type=ReplanningEventType.URGENT_REQUEST,
                        approval_status=ApprovalStatus.APPROVED,
                        request_id=urgent.id,
                        occurred_at=late,
                        approved_at=late,
                    )
                    current = Plan(
                        id=uuid.uuid7(),
                        region=region,
                        planning_date=today,
                        upload_id=upload.id,
                        kind=PlanKind.EVENT_REPLAN,
                        mode=DistributionMode.MIN_ENGINEERS,
                        strategy=PlanStrategy.LAYERED_GRAPH,
                        approval_status=ApprovalStatus.APPROVED,
                        based_on_plan_id=initial.id,
                        triggered_by_event_id=approved_event.id,
                        approved_at=late,
                        calculation_cutoff_at=morning,
                        assigned_requests_count=2,
                        unassigned_requests_count=0,
                        engineers_used_count=1,
                        total_mileage_km=Decimal("2.00"),
                    )
                    session.add(urgent)
                    await session.flush()
                    session.add(approved_event)
                    await session.flush()
                    session.add(current)
                    await session.flush()
                    self._stop(session, current.id, engineer.id, request.id, 1, morning)
                    self._stop(
                        session, current.id, engineer.id, urgent.id, 2, morning + timedelta(hours=1)
                    )
                    session.add(
                        PlanEngineerState(
                            plan_id=current.id, engineer_id=engineer.id, is_available=True
                        )
                    )
                    session.add_all(
                        [
                            ReplanningEvent(
                                id=uuid.uuid7(),
                                region=region,
                                planning_date=today,
                                event_type=ReplanningEventType.ENGINEER_UNAVAILABLE,
                                approval_status=ApprovalStatus.PENDING,
                                engineer_id=engineer.id,
                                occurred_at=late,
                            ),
                            ReplanningEvent(
                                id=uuid.uuid7(),
                                region=region,
                                planning_date=today,
                                event_type=ReplanningEventType.ENGINEER_AVAILABLE,
                                approval_status=ApprovalStatus.REJECTED,
                                engineer_id=engineer.id,
                                occurred_at=late,
                                rejected_at=late,
                            ),
                            Plan(
                                id=uuid.uuid7(),
                                region=region,
                                planning_date=today,
                                upload_id=upload.id,
                                kind=PlanKind.REPLAN,
                                mode=DistributionMode.MIN_ENGINEERS,
                                strategy=PlanStrategy.LAYERED_GRAPH,
                                approval_status=ApprovalStatus.PENDING,
                                based_on_plan_id=current.id,
                                calculation_cutoff_at=morning,
                                assigned_requests_count=99,
                                unassigned_requests_count=0,
                                engineers_used_count=1,
                                total_mileage_km=Decimal("99.00"),
                            ),
                            Plan(
                                id=uuid.uuid7(),
                                region=region,
                                planning_date=today,
                                upload_id=upload.id,
                                kind=PlanKind.REPLAN,
                                mode=DistributionMode.MIN_ENGINEERS,
                                strategy=PlanStrategy.LAYERED_GRAPH,
                                approval_status=ApprovalStatus.REJECTED,
                                based_on_plan_id=current.id,
                                rejected_at=late,
                                calculation_cutoff_at=morning,
                                assigned_requests_count=99,
                                unassigned_requests_count=0,
                                engineers_used_count=1,
                                total_mileage_km=Decimal("99.00"),
                            ),
                        ]
                    )
            await session.commit()

        async with self.sessions() as session:
            uow = UnitOfWork(session)
            service = DailyReportService(uow)
            snapshot = await service.build_snapshot(today, generated_at=generated_at)
            empty = await service.build_snapshot(
                today - timedelta(days=1), generated_at=generated_at
            )
            after_shift = await service.build_snapshot(
                today,
                generated_at=datetime.combine(today, time(20), tzinfo=ZoneInfo("Europe/Moscow")),
            )
            latest = await uow.plans.get_by_id(snapshot.regions[0].current_plan_id)
            self.assertIsNotNone(latest)
            stops = await uow.plan_stops.get_by_plan_id(latest.id)
            unassigned = await uow.plan_unassigned_requests.get_by_plan_id(latest.id)
            states = await uow.plan_engineer_states.get_by_plan_id(latest.id)
            requests = await uow.requests.get_by_ids(
                {item.request_id for item in stops} | {item.request_id for item in unassigned}
            )
            engineers = await uow.engineers.get_by_ids({item.engineer_id for item in states})
            plan_metrics = PlanSnapshotAssembler.build(
                latest, requests, engineers, states, stops, unassigned
            ).metrics
        self.assertTrue(snapshot.day_in_progress)
        self.assertFalse(after_shift.day_in_progress)
        self.assertEqual(empty.regions, ())
        self.assertEqual(empty.summary.requests_count, 0)
        self.assertEqual(len(snapshot.regions), 2)
        east, south_east = snapshot.regions
        self.assertEqual(east.region, Region.VOSTOK)
        self.assertEqual(len(east.plans), 2)
        self.assertEqual(east.current_plan_id, east.plans[-1].id)
        self.assertEqual(len(east.events), 1)
        self.assertEqual(east.metrics.assigned_count, 2)
        self.assertEqual(east.metrics.work_minutes, 110)
        self.assertEqual(east.metrics.travel_minutes, 20)
        self.assertEqual(east.metrics.mileage_km, Decimal("2.00"))
        self.assertEqual(east.metrics.assigned_count, plan_metrics.assigned_requests_count)
        self.assertEqual(east.metrics.unassigned_count, plan_metrics.unassigned_requests_count)
        self.assertEqual(east.metrics.work_minutes, plan_metrics.total_work_minutes)
        self.assertEqual(east.metrics.travel_minutes, plan_metrics.total_travel_minutes)
        self.assertEqual(
            east.metrics.utilization_with_travel, plan_metrics.average_workload_with_travel
        )
        self.assertEqual(
            east.metrics.utilization_without_travel,
            plan_metrics.average_workload_without_travel,
        )
        self.assertEqual(east.changes[0].assigned_delta, 1)
        self.assertEqual(east.baseline.mileage_km, Decimal("2.00"))
        self.assertEqual(len(south_east.plans), 1)
        self.assertEqual(len(south_east.engineers), 2)
        self.assertEqual(sum(bool(item.stops) for item in south_east.engineers), 1)
        self.assertEqual(len(south_east.unassigned), 1)
        self.assertEqual(south_east.unassigned[0].reason, UnassignedReason.NO_TIME_SLOT)
        self.assertEqual(snapshot.summary.requests_count, 4)
        self.assertEqual(snapshot.summary.assigned_count, 3)
        self.assertEqual(snapshot.summary.unassigned_count, 1)
        self.assertEqual(snapshot.summary.mileage_km, Decimal("3.00"))
        self.assertEqual(snapshot.summary.engineers_count, 3)
        files = DailyPdfRenderer.render(snapshot)
        self.assertEqual(set(files), {"vostok.pdf", "yugo_vostok.pdf", "summary.pdf"})
        self.assertTrue(all(content.startswith(b"%PDF-") for content in files.values()))
        self.assertEqual(set(DailyPdfRenderer.render(empty)), {"summary.pdf"})
        long_route = tuple(
            replace(
                east.engineers[0].stops[0],
                sequence_number=number,
                address="Длинный адрес с кириллицей и деталями " * 10,
            )
            for number in range(1, 61)
        )
        stress_region = replace(
            east,
            engineers=(replace(east.engineers[0], stops=long_route),),
        )
        stress_pdf = DailyPdfRenderer.render(replace(snapshot, regions=(stress_region,)))[
            "vostok.pdf"
        ]
        self.assertTrue(stress_pdf.startswith(b"%PDF-"))
        output_dir = os.environ.get("T08_PDF_OUTPUT_DIR")
        if output_dir is not None:
            destination = Path(output_dir)
            destination.mkdir(parents=True, exist_ok=True)
            for filename, content in files.items():
                (destination / filename).write_bytes(content)
            (destination / "stress.pdf").write_bytes(stress_pdf)

    @staticmethod
    def _stop(session, plan_id, engineer_id, request_id, sequence, start) -> None:
        session.add(
            PlanStop(
                plan_id=plan_id,
                engineer_id=engineer_id,
                request_id=request_id,
                sequence_number=sequence,
                planned_arrival=start,
                planned_start=start,
                planned_finish=start + timedelta(minutes=30),
                travel_minutes=10,
                distance_km=Decimal("1.00"),
                is_locked=False,
            )
        )
