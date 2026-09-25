import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from src.api.exc.plans import (
    InitialPlanExpiredError,
    PlanBaseChangedError,
    PlanNotFoundError,
    PlanNotPendingError,
    PlanStateChangedError,
    PlanStopAlreadyStartedError,
    PlanWrongDayError,
)
from src.api.plans.diff import PlanDiffEngine
from src.api.plans.diff_dto import PlanSnapshotDTO
from src.api.plans.dto import BaselineMetricsDTO, PlanDetailDTO, PlanSummaryDTO
from src.api.plans.presenter import PlanPresenter
from src.api.plans.snapshot import PlanSnapshotAssembler
from src.config import cfg
from src.core.db.enums import ApprovalStatus, PlanKind, Region, ReplanningEventType, RequestStatus
from src.core.db.models import Plan, PlanStop, ReplanningEvent
from src.core.db.uow import UnitOfWork
from src.core.utils.initial_approval import InitialApprovalPolicy


class PlanService:
    """Читает снимки планов и проводит решение диспетчера."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def get_current(self, region: Region, planning_date: date | None = None) -> PlanDetailDTO:
        target_date = planning_date or datetime.now(ZoneInfo("Europe/Moscow")).date()
        plan = await self._uow.plans.get_current(region, target_date)
        if plan is None:
            raise PlanNotFoundError
        return await self._build_detail(plan, is_current=True)

    async def get_by_id(self, plan_id: uuid.UUID) -> PlanDetailDTO:
        plan = await self._uow.plans.get_by_id(plan_id)
        if plan is None:
            raise PlanNotFoundError
        current = await self._uow.plans.get_current(plan.region, plan.planning_date)
        return await self._build_detail(
            plan, is_current=current is not None and current.id == plan.id
        )

    async def list_by_region(self, region: Region) -> tuple[PlanSummaryDTO, ...]:
        plans = await self._uow.plans.list_by_region(region)
        current_ids = self._current_ids(plans)
        return tuple(self._summary(plan, plan.id in current_ids) for plan in plans)

    async def approve(self, plan_id: uuid.UUID) -> PlanSummaryDTO:
        plan = await self._lock_pending_plan(plan_id)
        now = datetime.now(UTC)
        decided_at = now.replace(tzinfo=None)
        local_now = now.astimezone(ZoneInfo("Europe/Moscow")).replace(tzinfo=None)
        await self._validate_approval(plan, local_now, decided_at)
        self._uow.plans.set_approval_status(plan, ApprovalStatus.APPROVED, decided_at)
        await self._reject_siblings(plan, decided_at)
        if plan.triggered_by_event_id is not None:
            event = await self._get_event(plan.triggered_by_event_id)
            self._uow.replanning_events.set_approval_status(
                event, ApprovalStatus.APPROVED, decided_at
            )
            await self._apply_event(event)
        await self._uow.commit()
        return self._summary(plan, is_current=True)

    async def reject(self, plan_id: uuid.UUID) -> PlanSummaryDTO:
        plan = await self._lock_pending_plan(plan_id)
        decided_at = datetime.now(UTC).replace(tzinfo=None)
        self._uow.plans.set_approval_status(plan, ApprovalStatus.REJECTED, decided_at)
        if plan.triggered_by_event_id is not None:
            event = await self._get_event(plan.triggered_by_event_id)
            self._uow.replanning_events.set_approval_status(
                event, ApprovalStatus.REJECTED, decided_at
            )
        await self._uow.commit()
        return self._summary(plan, is_current=False)

    async def _lock_pending_plan(self, plan_id: uuid.UUID) -> Plan:
        plan = await self._uow.plans.get_by_id(plan_id)
        if plan is None:
            raise PlanNotFoundError
        await self._uow.plans.lock_region_day(plan.region, plan.planning_date)
        locked = await self._uow.plans.get_with_lock(plan_id)
        if locked is None:
            raise PlanNotFoundError
        if locked.approval_status != ApprovalStatus.PENDING:
            raise PlanNotPendingError
        return locked

    async def _validate_approval(
        self, plan: Plan, local_now: datetime, decided_at: datetime
    ) -> None:
        if plan.planning_date != local_now.date():
            raise PlanWrongDayError
        current = await self._uow.plans.get_current(plan.region, plan.planning_date)
        if plan.kind == PlanKind.INITIAL:
            if await self._uow.plans.has_approved_initial(plan.region, plan.planning_date):
                raise PlanBaseChangedError
            if not InitialApprovalPolicy.is_valid(plan.created_at, decided_at):
                raise InitialPlanExpiredError
        elif current is None or current.id != plan.based_on_plan_id:
            raise PlanBaseChangedError

        if await self._uow.replanning_events.list_approved_after(
            plan.region, plan.planning_date, self._cutoff_in_utc(plan.calculation_cutoff_at)
        ):
            raise PlanStateChangedError

        stops = await self._uow.plan_stops.get_by_plan_id(plan.id)
        unassigned = await self._uow.plan_unassigned_requests.get_by_plan_id(plan.id)
        request_ids = {item.request_id for item in stops} | {item.request_id for item in unassigned}
        requests = await self._uow.requests.get_by_ids_for_update(request_ids)
        if len(requests) != len(request_ids) or any(
            request.updated_at > plan.created_at for request in requests
        ):
            raise PlanStateChangedError

        states = await self._uow.plan_engineer_states.get_by_plan_id(plan.id)
        engineers = await self._uow.engineers.get_by_ids_for_update(
            {state.engineer_id for state in states}
        )
        available_by_id = {engineer.id: engineer.is_available for engineer in engineers}
        if len(available_by_id) != len(states) or any(
            available_by_id[state.engineer_id] != state.is_available for state in states
        ):
            raise PlanStateChangedError

        base_stops = (
            await self._uow.plan_stops.get_by_plan_id(plan.based_on_plan_id)
            if plan.based_on_plan_id is not None
            else []
        )
        self._validate_past_stops(stops, base_stops, local_now)

    @staticmethod
    def _cutoff_in_utc(cutoff: datetime) -> datetime:
        return cutoff.replace(tzinfo=ZoneInfo("Europe/Moscow")).astimezone(UTC).replace(tzinfo=None)

    @staticmethod
    def _validate_past_stops(
        stops: list[PlanStop], base_stops: list[PlanStop], now: datetime
    ) -> None:
        old_by_request = {stop.request_id: stop for stop in base_stops}
        new_by_request = {stop.request_id: stop for stop in stops}
        if any(
            old.planned_start < now and old.request_id not in new_by_request for old in base_stops
        ):
            raise PlanStopAlreadyStartedError
        for stop in stops:
            old = old_by_request.get(stop.request_id)
            if stop.planned_start >= now and (old is None or old.planned_start >= now):
                continue
            if (
                old is None
                or not stop.is_locked
                or (
                    stop.engineer_id,
                    stop.sequence_number,
                    stop.planned_arrival,
                    stop.planned_start,
                    stop.planned_finish,
                    stop.travel_minutes,
                    stop.distance_km,
                )
                != (
                    old.engineer_id,
                    old.sequence_number,
                    old.planned_arrival,
                    old.planned_start,
                    old.planned_finish,
                    old.travel_minutes,
                    old.distance_km,
                )
            ):
                raise PlanStopAlreadyStartedError

    async def _reject_siblings(self, plan: Plan, now: datetime) -> None:
        siblings = await self._uow.plans.list_pending(
            plan.region, plan.planning_date, exclude_plan_id=plan.id
        )
        for sibling in siblings:
            self._uow.plans.set_approval_status(sibling, ApprovalStatus.REJECTED, now)
            if sibling.triggered_by_event_id is not None:
                event = await self._get_event(sibling.triggered_by_event_id)
                self._uow.replanning_events.set_approval_status(event, ApprovalStatus.REJECTED, now)

    async def _get_event(self, event_id: uuid.UUID) -> ReplanningEvent:
        event = await self._uow.replanning_events.get_by_id(event_id)
        if event is None or event.approval_status != ApprovalStatus.PENDING:
            raise PlanStateChangedError
        return event

    async def _apply_event(self, event: ReplanningEvent) -> None:
        if event.event_type == ReplanningEventType.REQUEST_CANCELLED:
            if event.request_id is None:
                raise PlanStateChangedError
            request = await self._uow.requests.get_by_id(event.request_id)
            if request is None or request.status == RequestStatus.CANCELLED:
                raise PlanStateChangedError
            request.status = RequestStatus.CANCELLED
        elif event.event_type in (
            ReplanningEventType.ENGINEER_UNAVAILABLE,
            ReplanningEventType.ENGINEER_AVAILABLE,
        ):
            if event.engineer_id is None:
                raise PlanStateChangedError
            engineer = await self._uow.engineers.get_by_id(event.engineer_id)
            if engineer is None:
                raise PlanStateChangedError
            target_available = event.event_type == ReplanningEventType.ENGINEER_AVAILABLE
            if engineer.is_available == target_available:
                raise PlanStateChangedError
            engineer.is_available = target_available

    async def _build_detail(self, plan: Plan, is_current: bool) -> PlanDetailDTO:
        snapshot = await self._load_snapshot(plan)
        diff = None
        baseline_metrics = None
        if plan.kind == PlanKind.INITIAL:
            baseline = await self._uow.baseline_results.get_by_initial_plan_id(plan.id)
            if baseline is None and plan.approval_status != ApprovalStatus.APPROVED:
                raise ValueError("У initial-кандидата отсутствует BaselineResult")
            if baseline is not None:
                baseline_metrics = BaselineMetricsDTO(
                    assigned_requests_count=baseline.assigned_requests_count,
                    unassigned_requests_count=baseline.unassigned_requests_count,
                    engineers_used_count=baseline.engineers_used_count,
                    total_mileage_km=baseline.total_mileage_km,
                    average_workload_with_travel=baseline.average_workload_with_travel,
                    average_workload_without_travel=baseline.average_workload_without_travel,
                    algorithm_version=baseline.algorithm_version,
                )
        if plan.kind != PlanKind.INITIAL:
            if plan.based_on_plan_id is None:
                raise ValueError("Replan must reference its immutable base plan")
            base = await self._uow.plans.get_by_id(plan.based_on_plan_id)
            if base is None:
                raise PlanNotFoundError
            diff = PlanDiffEngine.compare(await self._load_snapshot(base), snapshot)
        return PlanPresenter.build_detail(
            snapshot=snapshot,
            is_current=is_current,
            approval_deadline=self._approval_deadline(plan),
            diff=diff,
            baseline_metrics=baseline_metrics,
            default_shift_start=cfg.planning.default_shift_start,
            default_shift_end=cfg.planning.default_shift_end,
        )

    async def _load_snapshot(self, plan: Plan) -> PlanSnapshotDTO:
        stops = await self._uow.plan_stops.get_by_plan_id(plan.id)
        unassigned = await self._uow.plan_unassigned_requests.get_by_plan_id(plan.id)
        plan_request_ids = {item.request_id for item in stops} | {
            item.request_id for item in unassigned
        }
        requests = await self._uow.requests.get_by_ids(plan_request_ids)

        engineers = await self._uow.engineers.get_by_upload_id(plan.upload_id)
        loaded_engineer_ids = {item.id for item in engineers}
        stop_engineer_ids = {item.engineer_id for item in stops}
        engineers.extend(
            await self._uow.engineers.get_by_ids(stop_engineer_ids - loaded_engineer_ids)
        )
        engineer_states = await self._uow.plan_engineer_states.get_by_plan_id(plan.id)
        return PlanSnapshotAssembler.build(
            plan, requests, engineers, engineer_states, stops, unassigned
        )

    @staticmethod
    def _summary(plan: Plan, is_current: bool) -> PlanSummaryDTO:
        return PlanSummaryDTO(
            id=plan.id,
            region=plan.region,
            planning_date=plan.planning_date,
            kind=plan.kind,
            approval_status=plan.approval_status,
            created_at=plan.created_at,
            approved_at=plan.approved_at,
            rejected_at=plan.rejected_at,
            approval_deadline=PlanService._approval_deadline(plan),
            based_on_plan_id=plan.based_on_plan_id,
            triggered_by_event_id=plan.triggered_by_event_id,
            is_current=is_current,
            assigned_requests_count=plan.assigned_requests_count,
            unassigned_requests_count=plan.unassigned_requests_count,
            engineers_used_count=plan.engineers_used_count,
            total_mileage_km=plan.total_mileage_km,
        )

    @staticmethod
    def _approval_deadline(plan: Plan) -> datetime | None:
        if plan.approval_status != ApprovalStatus.PENDING or plan.kind != PlanKind.INITIAL:
            return None
        return InitialApprovalPolicy.deadline(plan.created_at)

    @staticmethod
    def _current_ids(plans: list[Plan]) -> set[uuid.UUID]:
        current_by_date: dict[date, Plan] = {}
        for plan in plans:
            if plan.approval_status != ApprovalStatus.APPROVED or plan.approved_at is None:
                continue
            current = current_by_date.get(plan.planning_date)
            if current is None or (plan.approved_at, str(plan.id)) > (
                current.approved_at,
                str(current.id),
            ):
                current_by_date[plan.planning_date] = plan
        return {plan.id for plan in current_by_date.values()}
