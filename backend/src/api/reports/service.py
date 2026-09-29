import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.api.exc.reports import DailyReportGenerationError, DailyReportStorageError
from src.api.reports.dto import (
    DailyReportSnapshot,
    RegionReportSnapshot,
    ReportBaseline,
    ReportEngineer,
    ReportEvent,
    ReportMetrics,
    ReportPlanVersion,
    ReportStop,
    ReportUnassigned,
)
from src.api.reports.export import DailyReportZipBuilder
from src.api.reports.pdf import DailyPdfRenderer
from src.api.reports.presenter import ReportPresenter
from src.core.db.enums import PlanKind, Region
from src.core.db.models import BaselineResult, Engineer, Plan, PlanStop, ReplanningEvent, Request
from src.core.db.uow import UnitOfWork
from src.core.s3 import (
    ExportDownload,
    ExportKind,
    ExportTooLargeError,
    S3ExportDelivery,
    S3UnavailableError,
)


class DailyReportService:
    """Собирает плановый снимок дня исключительно из утверждённых решений."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def build_snapshot(
        self, planning_date: date, *, generated_at: datetime | None = None
    ) -> DailyReportSnapshot:
        generated_at = generated_at or datetime.now(ZoneInfo("Europe/Moscow"))
        if generated_at.tzinfo is None:
            raise ValueError("Время формирования отчёта должно содержать timezone")
        generated_at = generated_at.astimezone(ZoneInfo("Europe/Moscow"))
        approved_before = generated_at.astimezone(UTC).replace(tzinfo=None)
        plans = await self._uow.plans.list_approved_for_day(planning_date, approved_before)
        approved_event_ids = {
            plan.triggered_by_event_id for plan in plans if plan.triggered_by_event_id is not None
        }
        events = [
            event
            for event in await self._uow.replanning_events.list_approved_for_day(
                planning_date, approved_before
            )
            if event.id in approved_event_ids
        ]
        plans_by_region: dict[Region, list[Plan]] = defaultdict(list)
        events_by_region: dict[Region, list[ReplanningEvent]] = defaultdict(list)
        for plan in plans:
            plans_by_region[plan.region].append(plan)
        for event in events:
            events_by_region[event.region].append(event)

        event_requests = await self._uow.requests.get_by_ids(
            {item.request_id for item in events if item.request_id is not None}
        )
        event_engineers = await self._uow.engineers.get_by_ids(
            {item.engineer_id for item in events if item.engineer_id is not None}
        )
        requests_by_id = {item.id: item for item in event_requests}
        engineers_by_id = {item.id: item for item in event_engineers}
        regions = tuple(
            [
                await self._build_region(
                    region,
                    plans_by_region[region],
                    events_by_region[region],
                    requests_by_id,
                    engineers_by_id,
                )
                for region in Region
                if plans_by_region[region]
            ]
        )
        return DailyReportSnapshot(
            planning_date=planning_date,
            generated_at=generated_at,
            day_in_progress=planning_date == generated_at.date()
            and any(
                engineer.shift_end > generated_at.replace(tzinfo=None)
                for region in regions
                for engineer in region.engineers
            ),
            regions=regions,
            summary=ReportPresenter.summary(regions),
        )

    async def _build_region(
        self,
        region: Region,
        plans: list[Plan],
        events: list[ReplanningEvent],
        event_requests: dict[uuid.UUID, Request],
        event_engineers: dict[uuid.UUID, Engineer],
    ) -> RegionReportSnapshot:
        initial = next((item for item in plans if item.kind == PlanKind.INITIAL), None)
        if initial is None or initial.approved_at is None:
            raise ValueError("Для регионального отчёта нужен утверждённый initial")
        baseline = await self._uow.baseline_results.get_by_initial_plan_id(initial.id)
        if baseline is None:
            raise ValueError("У утверждённого initial отсутствует baseline")
        current = plans[-1]
        if current.approved_at is None:
            raise ValueError("Последний план не утверждён")
        versions = tuple(self._plan_version(item) for item in plans)
        initial_engineers, initial_unassigned = await self._final_routes(initial)
        initial_metrics = ReportPresenter.metrics(
            initial_engineers,
            initial.assigned_requests_count,
            initial.unassigned_requests_count,
        )
        self._validate_metrics(initial, initial_metrics, initial_engineers, initial_unassigned)
        engineers, unassigned = (
            (initial_engineers, initial_unassigned)
            if current.id == initial.id
            else await self._final_routes(current)
        )
        metrics = ReportPresenter.metrics(
            engineers, current.assigned_requests_count, current.unassigned_requests_count
        )
        self._validate_metrics(current, metrics, engineers, unassigned)
        return RegionReportSnapshot(
            region=region,
            planning_date=current.planning_date,
            initial_plan_id=initial.id,
            upload_id=initial.upload_id,
            initial_approved_at=initial.approved_at,
            baseline=self._baseline(baseline),
            initial_metrics=initial_metrics,
            plans=versions,
            changes=ReportPresenter.changes(versions),
            events=tuple(self._event(item, event_requests, event_engineers) for item in events),
            current_plan_id=current.id,
            current_approved_at=current.approved_at,
            engineers=engineers,
            unassigned=unassigned,
            metrics=metrics,
        )

    @staticmethod
    def _validate_metrics(
        plan: Plan,
        metrics: ReportMetrics,
        engineers: tuple[ReportEngineer, ...],
        unassigned: tuple[ReportUnassigned, ...],
    ) -> None:
        if (
            metrics.assigned_count != sum(len(item.stops) for item in engineers)
            or metrics.unassigned_count != len(unassigned)
            or metrics.engineers_used_count != plan.engineers_used_count
            or metrics.mileage_km != plan.total_mileage_km
        ):
            raise ValueError("Метрики плана не совпадают с сохранёнными маршрутами")

    async def _final_routes(
        self, plan: Plan
    ) -> tuple[tuple[ReportEngineer, ...], tuple[ReportUnassigned, ...]]:
        stops = await self._uow.plan_stops.get_by_plan_id(plan.id)
        unassigned = await self._uow.plan_unassigned_requests.get_by_plan_id(plan.id)
        states = await self._uow.plan_engineer_states.get_by_plan_id(plan.id)
        requests = await self._uow.requests.get_by_ids(
            {item.request_id for item in stops} | {item.request_id for item in unassigned}
        )
        engineers = await self._uow.engineers.get_by_ids({item.engineer_id for item in states})
        requests_by_id = {item.id: item for item in requests}
        engineers_by_id = {item.id: item for item in engineers}
        if len(requests_by_id) != len(stops) + len(unassigned) or len(engineers_by_id) != len(
            states
        ):
            raise ValueError(
                "Снимок последнего плана содержит отсутствующие или дублирующиеся записи"
            )
        stops_by_engineer: dict[uuid.UUID, list[PlanStop]] = defaultdict(list)
        for stop in stops:
            if stop.engineer_id not in engineers_by_id:
                raise ValueError("Остановка ссылается на неизвестного инженера")
            stops_by_engineer[stop.engineer_id].append(stop)
        route_engineers = tuple(
            self._engineer(
                engineers_by_id[state.engineer_id],
                state.is_available,
                stops_by_engineer[state.engineer_id],
                requests_by_id,
            )
            for state in sorted(states, key=lambda item: engineers_by_id[item.engineer_id].name)
        )
        missing = tuple(
            ReportUnassigned(
                external_id=requests_by_id[item.request_id].external_id,
                address=requests_by_id[item.request_id].address,
                reason=item.reason,
            )
            for item in sorted(
                unassigned, key=lambda item: requests_by_id[item.request_id].external_id
            )
        )
        return route_engineers, missing

    @staticmethod
    def _engineer(
        engineer: Engineer,
        is_available: bool,
        stops: list[PlanStop],
        requests: dict[uuid.UUID, Request],
    ) -> ReportEngineer:
        route = tuple(
            ReportStop(
                external_id=requests[stop.request_id].external_id,
                address=requests[stop.request_id].address,
                sequence_number=stop.sequence_number,
                planned_arrival=stop.planned_arrival,
                planned_start=stop.planned_start,
                planned_finish=stop.planned_finish,
                work_minutes=requests[stop.request_id].norm_minutes_without_travel,
                travel_minutes=stop.travel_minutes,
                distance_km=stop.distance_km,
                is_locked=stop.is_locked,
            )
            for stop in sorted(stops, key=lambda item: item.sequence_number)
        )
        work = sum(item.work_minutes for item in route)
        travel = sum(item.travel_minutes for item in route)
        shift = int((engineer.shift_end - engineer.shift_start).total_seconds() // 60)
        return ReportEngineer(
            id=engineer.id,
            name=engineer.name,
            shift_start=engineer.shift_start,
            shift_end=engineer.shift_end,
            is_available=is_available,
            work_minutes=work,
            travel_minutes=travel,
            mileage_km=sum((item.distance_km for item in route), Decimal("0")),
            utilization_with_travel=DailyReportService._utilization(work + travel, shift),
            utilization_without_travel=DailyReportService._utilization(work, shift),
            stops=route,
        )

    @staticmethod
    def _utilization(minutes: int, shift_minutes: int) -> Decimal:
        if shift_minutes <= 0:
            return Decimal("0")
        return (Decimal(minutes) * Decimal("100") / Decimal(shift_minutes)).quantize(
            Decimal("0.01")
        )

    @staticmethod
    def _plan_version(plan: Plan) -> ReportPlanVersion:
        if plan.approved_at is None:
            raise ValueError("В хронологию попал неутверждённый план")
        return ReportPlanVersion(
            id=plan.id,
            kind=plan.kind,
            approved_at=plan.approved_at,
            assigned_count=plan.assigned_requests_count,
            unassigned_count=plan.unassigned_requests_count,
            engineers_used_count=plan.engineers_used_count,
            mileage_km=plan.total_mileage_km,
            based_on_plan_id=plan.based_on_plan_id,
        )

    @staticmethod
    def _baseline(baseline: BaselineResult) -> ReportBaseline:
        return ReportBaseline(
            assigned_count=baseline.assigned_requests_count,
            unassigned_count=baseline.unassigned_requests_count,
            engineers_used_count=baseline.engineers_used_count,
            mileage_km=baseline.total_mileage_km,
            utilization_with_travel=baseline.average_workload_with_travel,
            utilization_without_travel=baseline.average_workload_without_travel,
        )

    @staticmethod
    def _event(
        event: ReplanningEvent,
        requests: dict[uuid.UUID, Request],
        engineers: dict[uuid.UUID, Engineer],
    ) -> ReportEvent:
        if event.approved_at is None:
            raise ValueError("В хронологию попало неутверждённое событие")
        if event.request_id is not None:
            request = requests.get(event.request_id)
            if request is None:
                raise ValueError("Целевая заявка события не найдена")
            target = f"Заявка №{request.external_id}"
        elif event.engineer_id is not None:
            engineer = engineers.get(event.engineer_id)
            if engineer is None:
                raise ValueError("Целевой инженер события не найден")
            target = engineer.name
        else:
            raise ValueError("Событие не содержит цель")
        return ReportEvent(
            id=event.id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            approved_at=event.approved_at,
            target=target,
        )


class DailyReportExportService:
    """Собирает дневной PDF-пакет и доставляет его по временной ссылке."""

    def __init__(self, reports: DailyReportService, delivery: S3ExportDelivery) -> None:
        self._reports = reports
        self._delivery = delivery

    async def export(self, planning_date: date) -> ExportDownload:
        try:
            snapshot = await self._reports.build_snapshot(planning_date)
            files = DailyPdfRenderer.render(snapshot)
            data = DailyReportZipBuilder.build(
                planning_date,
                files,
                tuple(region.region.value for region in snapshot.regions),
            )
            return await self._delivery.deliver(
                data=data,
                kind=ExportKind.DAILY_REPORT,
                planning_date=planning_date,
                filename=f"daily-report-{planning_date.isoformat()}.zip",
                content_type="application/zip",
            )
        except (ValueError, OSError, ExportTooLargeError) as exc:
            raise DailyReportGenerationError from exc
        except S3UnavailableError as exc:
            raise DailyReportStorageError from exc
