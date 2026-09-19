from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from beeline_backend.application.contracts import (
    DayReport,
    ImportedDataset,
    PlanningSnapshot,
    RouteMatrix,
)
from beeline_backend.domain.model import PlanCandidate, RequestStatus


class Clock(Protocol):
    def now(self) -> datetime: ...


class DatasetImporter(Protocol):
    def parse(self, filename: str, content: bytes) -> ImportedDataset: ...


class GeocodingProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def geocode(self, address: str, region: str) -> tuple[float, float]: ...


class RoutingProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def matrix(
        self, coordinates: list[tuple[float, float]], profile: str, departure_at: datetime
    ) -> RouteMatrix: ...

    async def route_geometry(
        self, coordinates: list[tuple[float, float]], profile: str
    ) -> dict[str, object]: ...


class PlanningAlgorithm(Protocol):
    @property
    def name(self) -> str: ...

    async def plan(self, snapshot: PlanningSnapshot) -> PlanCandidate: ...


class ReportRenderer(Protocol):
    media_type: str
    extension: str

    def render(self, report: DayReport, destination: Path) -> None: ...


class Gateway(Protocol):
    async def persist_import(
        self, dataset: ImportedDataset, idempotency_key: str | None
    ) -> dict[str, object]: ...

    async def list_scenarios(self) -> list[dict[str, object]]: ...
    async def list_requests(
        self, scenario_id: UUID, planning_date: date, limit: int, offset: int
    ) -> list[dict[str, object]]: ...
    async def get_request(self, request_id: UUID) -> dict[str, object]: ...
    async def list_engineers(self, scenario_id: UUID) -> list[dict[str, object]]: ...
    async def create_request(
        self,
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
    ) -> dict[str, object]: ...
    async def build_snapshot(
        self, scenario_id: UUID, planning_date: date, as_of: datetime, base_plan_id: UUID | None
    ) -> PlanningSnapshot: ...
    async def attach_matrix(self, snapshot: PlanningSnapshot, matrix: RouteMatrix) -> PlanningSnapshot: ...
    async def start_run(self, snapshot: PlanningSnapshot, algorithm: str) -> UUID: ...
    async def save_candidate(
        self,
        run_id: UUID,
        snapshot: PlanningSnapshot,
        candidate: PlanCandidate,
        algorithm: str,
        route_geometries: dict[UUID, dict[str, object]],
    ) -> tuple[UUID, UUID]: ...
    async def mark_run_failed(self, run_id: UUID, code: str, message: str) -> None: ...
    async def approve_plan(
        self, plan_id: UUID, expected_base_plan_id: UUID | None, actor: str
    ) -> dict[str, object]: ...
    async def list_plans(
        self, scenario_id: UUID, planning_date: date
    ) -> list[dict[str, object]]: ...
    async def get_plan(self, plan_id: UUID) -> dict[str, object]: ...
    async def get_run(self, run_id: UUID) -> dict[str, object]: ...
    async def record_fact(
        self,
        request_id: UUID,
        status: RequestStatus,
        effective_at: datetime,
        actor: str,
        reason: str,
        actual_start: datetime | None,
        actual_finish: datetime | None,
    ) -> dict[str, object]: ...
    async def create_event(
        self,
        scenario_id: UUID,
        planning_date: date,
        event_type: str,
        effective_at: datetime,
        payload: dict[str, object],
        idempotency_key: str,
        actor: str,
    ) -> dict[str, object]: ...
    async def start_event_replanning(self, event_id: UUID, job_key: str) -> None: ...
    async def complete_event_replanning(
        self, event_id: UUID, job_key: str, result: dict[str, object]
    ) -> None: ...
    async def fail_event_replanning(
        self, event_id: UUID, job_key: str, error_code: str
    ) -> None: ...
    async def diff_plans(self, old_plan_id: UUID, new_plan_id: UUID) -> dict[str, object]: ...
    async def manual_change(
        self,
        plan_id: UUID,
        request_id: UUID,
        engineer_id: UUID,
        position: int,
        start_at: datetime | None,
        reason: str,
        actor: str,
    ) -> UUID: ...
    async def route_coordinate_sets(
        self, plan_id: UUID
    ) -> dict[UUID, list[tuple[float, float]]]: ...
    async def store_route_geometries(
        self, plan_id: UUID, geometries: dict[UUID, dict[str, object]]
    ) -> None: ...
    async def build_report(self, plan_id: UUID, now: datetime) -> DayReport: ...
    async def get_audit(
        self, scenario_id: UUID, limit: int, offset: int
    ) -> list[dict[str, object]]: ...
