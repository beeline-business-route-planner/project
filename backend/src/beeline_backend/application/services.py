from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from beeline_backend.application.contracts import ManualChangeContext
from beeline_backend.application.planner import validate_candidate
from beeline_backend.application.ports import (
    Clock,
    DatasetImporter,
    Gateway,
    PlanningAlgorithm,
    ReportRenderer,
    RoutingProvider,
)
from beeline_backend.application.routing import RouteBuilder
from beeline_backend.domain.errors import DomainError
from beeline_backend.domain.model import RequestStatus


class BackendService:
    def __init__(
        self,
        gateway: Gateway,
        importer: DatasetImporter,
        router: RoutingProvider,
        planner: PlanningAlgorithm,
        clock: Clock,
        route_builder: RouteBuilder,
        warm_routes: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self.gateway = gateway
        self._importer = importer
        self._router = router
        self._planner = planner
        self._clock = clock
        self._route_builder = route_builder
        self._warm_routes = warm_routes

    async def import_dataset(
        self, filename: str, content: bytes, idempotency_key: str | None
    ) -> dict[str, object]:
        parsed = self._importer.parse(filename, content)
        return await self.gateway.persist_import(parsed, idempotency_key)

    async def run_plan(
        self,
        scenario_id: UUID,
        planning_date: date,
        base_plan_id: UUID | None,
        as_of: datetime | None = None,
    ) -> dict[str, object]:
        effective_as_of = as_of or self._clock.now()
        snapshot = await self.gateway.build_snapshot(
            scenario_id, planning_date, effective_as_of, base_plan_id
        )
        run_id = await self.gateway.start_run(snapshot, self._planner.name)
        try:
            coordinates = [(item.latitude, item.longitude) for item in snapshot.locations]
            matrix = await self._router.matrix(coordinates, "driving", effective_as_of)
            snapshot = await self.gateway.attach_matrix(snapshot, matrix)
            candidate = await self._planner.plan(snapshot)
            validate_candidate(snapshot, candidate)
            route_build = await self._route_builder.build(snapshot, candidate)
            run_id, plan_id = await self.gateway.save_candidate(
                run_id,
                snapshot,
                candidate,
                self._planner.name,
                route_build.legacy_geometries,
                snapshot.base_plan_id,
                route_build,
            )
        except asyncio.CancelledError:
            await self.gateway.mark_run_failed(
                run_id, "planning_cancelled", "Planning run was cancelled"
            )
            raise
        except DomainError as exc:
            await self.gateway.mark_run_failed(run_id, exc.code, exc.message)
            raise
        except Exception:
            await self.gateway.mark_run_failed(run_id, "unexpected_planning_error", "Unexpected planning failure")
            raise
        logging.getLogger(__name__).info("plan_routes_persisted", extra={"fields": {
            "plan_id": str(plan_id), "run_id": str(run_id),
            "segments_reused": route_build.segments_reused, "segments_calculated": route_build.segments_calculated,
        }})
        if self._warm_routes is not None:
            await self._warm_routes(plan_id)
        return {"planning_run_id": run_id, "plan_id": plan_id, "status": "succeeded"}

    async def create_request_and_replan(
        self,
        *,
        scenario_id: UUID,
        planning_date: date,
        external_id: str,
        address: str,
        district: str,
        window_start: datetime,
        window_end: datetime,
        service_minutes: int,
        required_skill: str,
        required_transport: str | None,
        priority: str,
        idempotency_key: str,
        actor: str,
    ) -> dict[str, object]:
        created = await self.gateway.create_request(
            scenario_id,
            planning_date,
            external_id,
            address,
            district,
            window_start,
            window_end,
            service_minutes,
            required_skill,
            required_transport,
            priority,
            idempotency_key,
            actor,
        )
        plans = await self.gateway.list_plans(scenario_id, planning_date)
        active = next((item for item in plans if item["status"] == "approved"), None)
        if created["duplicate"]:
            return {**created, "replanning": None}
        replanning = await self.run_plan(
            scenario_id,
            planning_date,
            active["id"] if active else None,  # type: ignore[arg-type]
        )
        return {**created, "replanning": replanning}

    async def create_event_and_replan(
        self,
        scenario_id: UUID,
        planning_date: date,
        event_type: str,
        effective_at: datetime,
        payload: dict[str, object],
        idempotency_key: str,
        actor: str,
    ) -> dict[str, object]:
        event = await self.gateway.create_event(
            scenario_id,
            planning_date,
            event_type,
            effective_at,
            payload,
            idempotency_key,
            actor,
        )
        event_id = event.get("event_id")
        job_key = event.get("job_key")
        if not isinstance(event_id, UUID) or not isinstance(job_key, str):
            raise DomainError(
                "invalid_event_processing_state",
                "Event processing metadata is incomplete",
            )
        duplicate = event.get("duplicate") is True
        cached_replanning = event.get("replanning")
        if duplicate and isinstance(cached_replanning, dict):
            return {
                "event_id": event_id,
                "duplicate": True,
                "replanning": cached_replanning,
            }
        await self.gateway.start_event_replanning(event_id, job_key)
        try:
            plans = await self.gateway.list_plans(scenario_id, planning_date)
            active = next((item for item in plans if item["status"] == "approved"), None)
            replanning = await self.run_plan(
                scenario_id,
                planning_date,
                active["id"] if active else None,  # type: ignore[arg-type]
                effective_at,
            )
        except asyncio.CancelledError:
            await self.gateway.fail_event_replanning(event_id, job_key, "planning_cancelled")
            raise
        except DomainError as exc:
            await self.gateway.fail_event_replanning(event_id, job_key, exc.code)
            raise
        except Exception as exc:
            await self.gateway.fail_event_replanning(event_id, job_key, type(exc).__name__)
            raise
        await self.gateway.complete_event_replanning(event_id, job_key, replanning)
        return {"event_id": event_id, "duplicate": duplicate, "replanning": replanning}

    async def record_fact(
        self,
        request_id: UUID,
        status: RequestStatus,
        effective_at: datetime,
        actor: str,
        reason: str,
        actual_start: datetime | None,
        actual_finish: datetime | None,
    ) -> dict[str, object]:
        return await self.gateway.record_fact(
            request_id,
            status,
            effective_at,
            actor,
            reason,
            actual_start,
            actual_finish,
        )

    async def manual_change(
        self,
        plan_id: UUID,
        request_id: UUID,
        engineer_id: UUID,
        position: int,
        start_at: datetime | None,
        reason: str,
        actor: str,
    ) -> UUID:
        prepared = await self.gateway.prepare_manual_change(
            plan_id, request_id, engineer_id, position, start_at, reason, actor,
        )
        run_id = await self.gateway.start_run(prepared.snapshot, "manual-dispatcher-v1")
        try:
            route_build = await self._route_builder.build(prepared.snapshot, prepared.candidate)
            _, new_plan_id = await self.gateway.save_candidate(
                run_id, prepared.snapshot, prepared.candidate, "manual-dispatcher-v1",
                route_build.legacy_geometries, plan_id, route_build,
                ManualChangeContext(plan_id, prepared.parent_version, request_id, actor, reason),
            )
        except asyncio.CancelledError:
            await self.gateway.mark_run_failed(run_id, "planning_cancelled", "Manual routing was cancelled")
            raise
        except DomainError as exc:
            await self.gateway.mark_run_failed(run_id, exc.code, exc.message)
            raise
        except Exception:
            await self.gateway.mark_run_failed(run_id, "unexpected_planning_error", "Manual routing failed")
            raise
        if self._warm_routes is not None:
            await self._warm_routes(new_plan_id)
        return new_plan_id

    async def render_report(
        self, plan_id: UUID, renderer: ReportRenderer, destination: Path
    ) -> Path:
        report = await self.gateway.build_report(plan_id, self._clock.now())
        renderer.render(report, destination)
        return destination
