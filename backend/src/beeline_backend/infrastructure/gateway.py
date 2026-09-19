from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime, time
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from beeline_backend.application.contracts import (
    DayReport,
    EngineerData,
    ImportedDataset,
    LocationData,
    LockedAssignmentData,
    PlanningSnapshot,
    ReportAssignment,
    RequestData,
    RouteMatrix,
    TravelSnapshot,
)
from beeline_backend.application.planner import validate_candidate
from beeline_backend.application.ports import Clock, GeocodingProvider
from beeline_backend.domain.errors import ConflictError, DomainError, NotFoundError
from beeline_backend.domain.model import (
    Assignment,
    PlanCandidate,
    RequestStatus,
    Unassigned,
    VisitWindow,
    calculate_visit,
    validate_status_transition,
)
from beeline_backend.infrastructure.models import (
    AssignmentRow,
    AuditLogRow,
    DatasetRow,
    DayEventRow,
    EngineerRow,
    EngineerSkillRow,
    ImportErrorRow,
    LocationRow,
    OutboxJobRow,
    PlanApprovalRow,
    PlanMetricRow,
    PlanningRunRow,
    PlanRow,
    RequestRow,
    RequestStatusEventRow,
    RouteLegRow,
    ScenarioRow,
    ShiftRow,
    SkillRow,
    TransportTypeRow,
    UnassignedRequestRow,
    WorkTypeRow,
)


def _normalize_address(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[.,]", " ", value.casefold())).strip()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _with_zone(value: datetime, timezone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).astimezone(timezone)
    return value.astimezone(timezone)


class SqlGateway:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        geocoder: GeocodingProvider,
        timezone: str,
    ) -> None:
        self._session = session
        self._clock = clock
        self._geocoder = geocoder
        self._timezone = ZoneInfo(timezone)

    def _now(self) -> datetime:
        return self._clock.now()

    async def _audit(
        self,
        scenario_id: UUID,
        action: str,
        object_type: str,
        object_id: UUID | str,
        actor: str,
        reason: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        now = self._now()
        self._session.add(
            AuditLogRow(
                scenario_id=scenario_id,
                action=action,
                actor=actor,
                source="api",
                effective_at=now,
                recorded_at=now,
                object_type=object_type,
                object_id=str(object_id),
                object_version=1,
                reason=reason,
                details=details or {},
            )
        )

    async def _seed_references(self) -> dict[str, WorkTypeRow]:
        skills = {
            "connection": "Работы на подключение и дозаказы",
            "emergency": "Аварийные работы",
            "local": "Локальные работы",
        }
        for code, name in skills.items():
            if await self._session.get(SkillRow, code) is None:
                self._session.add(SkillRow(code=code, name=name))
        transports = {
            "car": ("Автомобиль", "driving"),
            "walking": ("Пешеход", "walking"),
            "bicycle": ("Велосипед", "cycling"),
            "transit": ("Общественный транспорт", "transit"),
        }
        for code, (name, profile) in transports.items():
            if await self._session.get(TransportTypeRow, code) is None:
                self._session.add(TransportTypeRow(code=code, name=name, routing_profile=profile))
        work_types = {
            "connection": ("Базовое подключение", 70, 90, "connection"),
            "emergency": ("Авария на ТКД", 80, 100, "emergency"),
            "equipment_order": ("Дозаказ оборудования", 20, 40, "connection"),
            "local": ("Локальная заявка/ремонт", 30, 50, "local"),
        }
        result: dict[str, WorkTypeRow] = {}
        for code, (name, service, full, skill) in work_types.items():
            row = await self._session.scalar(select(WorkTypeRow).where(WorkTypeRow.code == code))
            if row is None:
                row = WorkTypeRow(
                    code=code,
                    name=name,
                    service_minutes=service,
                    full_normative_minutes=full,
                    required_skill_code=skill,
                )
                self._session.add(row)
            result[code] = row
        await self._session.flush()
        return result

    async def _get_or_create_location(self, address: str, region: str) -> LocationRow:
        normalized = _normalize_address(address)
        row = await self._session.scalar(
            select(LocationRow).where(
                LocationRow.normalized_address == normalized, LocationRow.region == region
            )
        )
        if row is not None:
            return row
        latitude, longitude = await self._geocoder.geocode(address, region)
        row = LocationRow(
            address=address,
            normalized_address=normalized,
            region=region,
            latitude=latitude,
            longitude=longitude,
            coordinate_source=self._geocoder.name,
            coordinate_version=1,
            created_at=self._now(),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def _seed_engineers(
        self, scenario: ScenarioRow, office: LocationRow, planning_date: date
    ) -> None:
        existing = await self._session.scalar(
            select(func.count()).select_from(EngineerRow).where(EngineerRow.scenario_id == scenario.id)
        )
        if existing:
            return
        for index in range(1, 13):
            engineer = EngineerRow(
                scenario_id=scenario.id,
                external_code=f"{scenario.code}-eng-{index:02d}",
                name=f"Инженер {scenario.name} {index:02d}",
                transport_code="car",
                home_location_id=office.id,
                active=True,
                version=1,
                created_at=self._now(),
            )
            self._session.add(engineer)
            await self._session.flush()
            skill_sets = {
                0: ("connection", "emergency", "local"),
                1: ("connection", "local"),
                2: ("emergency", "local"),
                3: ("connection", "emergency"),
            }
            for skill in skill_sets[index % 4]:
                self._session.add(EngineerSkillRow(engineer_id=engineer.id, skill_code=skill))
            self._session.add(
                ShiftRow(
                    engineer_id=engineer.id,
                    shift_date=planning_date,
                    start_time=time(8, 0),
                    end_time=time(23, 0),
                    available=True,
                )
            )

    async def persist_import(
        self, dataset: ImportedDataset, idempotency_key: str | None
    ) -> dict[str, object]:
        if idempotency_key:
            existing_by_key = await self._session.scalar(
                select(DatasetRow).where(DatasetRow.idempotency_key == idempotency_key)
            )
            if existing_by_key is not None:
                return {
                    "dataset_id": existing_by_key.id,
                    "scenario_id": existing_by_key.scenario_id,
                    "duplicate": True,
                    "issues": [],
                }
        scenario = await self._session.scalar(
            select(ScenarioRow).where(ScenarioRow.code == dataset.scenario_code)
        )
        now = self._now()
        if scenario is None:
            scenario = ScenarioRow(
                code=dataset.scenario_code,
                name=dataset.scenario_name,
                timezone=str(self._timezone),
                office_location_id=None,
                created_at=now,
            )
            self._session.add(scenario)
            await self._session.flush()
        existing = await self._session.scalar(
            select(DatasetRow).where(
                DatasetRow.scenario_id == scenario.id, DatasetRow.sha256 == dataset.sha256
            )
        )
        if existing is not None:
            return {
                "dataset_id": existing.id,
                "scenario_id": scenario.id,
                "duplicate": True,
                "issues": [],
            }
        work_types = await self._seed_references()
        office = await self._get_or_create_location(dataset.office_address, "Москва")
        scenario.office_location_id = office.id
        row = DatasetRow(
            scenario_id=scenario.id,
            planning_date=dataset.planning_date,
            source_name=dataset.source_name,
            sha256=dataset.sha256,
            status="accepted_with_warnings" if dataset.issues else "accepted",
            imported_at=now,
            idempotency_key=idempotency_key,
            raw_metadata={"request_count": len(dataset.requests)},
        )
        self._session.add(row)
        await self._session.flush()
        for issue in dataset.issues:
            self._session.add(
                ImportErrorRow(
                    dataset_id=row.id,
                    file_name=issue.file,
                    sheet_name=issue.sheet,
                    row_number=issue.row,
                    field_name=issue.field,
                    reason_code=issue.reason_code,
                    message=issue.message,
                )
            )
        for item in dataset.requests:
            location = await self._get_or_create_location(item.address, "Москва")
            work_type = work_types.get(item.work_code or "")
            request = RequestRow(
                scenario_id=scenario.id,
                dataset_id=row.id,
                location_id=location.id,
                external_id=item.external_id,
                planning_date=dataset.planning_date,
                bk_type=item.bk_type,
                hd_type=item.hd_type,
                district=item.district,
                window_start=_as_utc(item.window_start),
                window_end=_as_utc(item.window_end),
                work_type_id=work_type.id if work_type else None,
                service_minutes=item.service_minutes,
                full_normative_minutes=item.full_normative_minutes,
                required_skill_code=item.required_skill,
                required_transport_code=None,
                priority="normal",
                mapping_state=item.mapping_state,
                gigabit=item.gigabit,
                connection_kind=item.connection_kind,
                version=1,
                created_at=now,
            )
            self._session.add(request)
            await self._session.flush()
            self._session.add(
                RequestStatusEventRow(
                    request_id=request.id,
                    status=RequestStatus.NOT_SENT.value,
                    source="import",
                    actor="system",
                    effective_at=now,
                    recorded_at=now,
                    actual_start=None,
                    actual_finish=None,
                    reason="Initial imported status",
                    corrects_event_id=None,
                    idempotency_key=f"import:{row.id}:{request.external_id}",
                )
            )
        await self._seed_engineers(scenario, office, dataset.planning_date)
        await self._audit(
            scenario.id,
            "dataset_imported",
            "dataset",
            row.id,
            "system",
            details={"requests": len(dataset.requests), "issues": len(dataset.issues)},
        )
        await self._session.commit()
        return {
            "dataset_id": row.id,
            "scenario_id": scenario.id,
            "duplicate": False,
            "request_count": len(dataset.requests),
            "issues": [issue.model_dump(mode="json") for issue in dataset.issues],
        }

    async def list_scenarios(self) -> list[dict[str, object]]:
        rows = (
            await self._session.scalars(select(ScenarioRow).order_by(ScenarioRow.name))
        ).all()
        result: list[dict[str, object]] = []
        for row in rows:
            dates = (
                await self._session.scalars(
                    select(DatasetRow.planning_date)
                    .where(DatasetRow.scenario_id == row.id)
                    .distinct()
                    .order_by(DatasetRow.planning_date)
                )
            ).all()
            result.append(
                {
                    "id": row.id,
                    "code": row.code,
                    "name": row.name,
                    "timezone": row.timezone,
                    "planning_dates": dates,
                }
            )
        return result

    async def _latest_statuses(self, request_ids: list[UUID]) -> dict[UUID, RequestStatusEventRow]:
        if not request_ids:
            return {}
        events = (
            await self._session.scalars(
                select(RequestStatusEventRow)
                .where(RequestStatusEventRow.request_id.in_(request_ids))
                .order_by(RequestStatusEventRow.request_id, RequestStatusEventRow.recorded_at)
            )
        ).all()
        result: dict[UUID, RequestStatusEventRow] = {}
        for event in events:
            result[event.request_id] = event
        return result

    async def list_requests(
        self, scenario_id: UUID, planning_date: date, limit: int, offset: int
    ) -> list[dict[str, object]]:
        rows = (
            await self._session.execute(
                select(RequestRow, LocationRow)
                .join(LocationRow, RequestRow.location_id == LocationRow.id)
                .where(
                    RequestRow.scenario_id == scenario_id,
                    RequestRow.planning_date == planning_date,
                )
                .order_by(RequestRow.window_start, RequestRow.external_id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        statuses = await self._latest_statuses([request.id for request, _ in rows])
        return [
            {
                "id": request.id,
                "external_id": request.external_id,
                "address": location.address,
                "window_start": request.window_start,
                "window_end": request.window_end,
                "service_minutes": request.service_minutes,
                "status": statuses[request.id].status,
                "mapping_state": request.mapping_state,
            }
            for request, location in rows
        ]

    async def get_request(self, request_id: UUID) -> dict[str, object]:
        pair = (
            await self._session.execute(
                select(RequestRow, LocationRow)
                .join(LocationRow, RequestRow.location_id == LocationRow.id)
                .where(RequestRow.id == request_id)
            )
        ).first()
        if pair is None:
            raise NotFoundError("request_not_found", "Request not found", {"id": str(request_id)})
        request, location = pair
        events = (
            await self._session.scalars(
                select(RequestStatusEventRow)
                .where(RequestStatusEventRow.request_id == request_id)
                .order_by(RequestStatusEventRow.recorded_at)
            )
        ).all()
        return {
            "id": request.id,
            "external_id": request.external_id,
            "bk_type": request.bk_type,
            "hd_type": request.hd_type,
            "address": location.address,
            "coordinates": [location.longitude, location.latitude],
            "window_start": request.window_start,
            "window_end": request.window_end,
            "service_minutes": request.service_minutes,
            "full_normative_minutes": request.full_normative_minutes,
            "mapping_state": request.mapping_state,
            "status_history": [
                {
                    "id": event.id,
                    "status": event.status,
                    "source": event.source,
                    "actor": event.actor,
                    "effective_at": event.effective_at,
                    "recorded_at": event.recorded_at,
                    "reason": event.reason,
                }
                for event in events
            ],
        }

    async def list_engineers(self, scenario_id: UUID) -> list[dict[str, object]]:
        rows = (
            await self._session.scalars(
                select(EngineerRow)
                .where(EngineerRow.scenario_id == scenario_id, EngineerRow.active.is_(True))
                .order_by(EngineerRow.name)
            )
        ).all()
        result: list[dict[str, object]] = []
        for row in rows:
            skills = (
                await self._session.scalars(
                    select(EngineerSkillRow.skill_code).where(EngineerSkillRow.engineer_id == row.id)
                )
            ).all()
            result.append(
                {
                    "id": row.id,
                    "external_code": row.external_code,
                    "name": row.name,
                    "transport": row.transport_code,
                    "skills": list(skills),
                }
            )
        return result

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
    ) -> dict[str, object]:
        if window_end <= window_start:
            raise DomainError("invalid_window", "Window end must be after start")
        dataset = await self._session.scalar(
            select(DatasetRow)
            .where(DatasetRow.scenario_id == scenario_id, DatasetRow.planning_date == planning_date)
            .order_by(DatasetRow.imported_at.desc())
            .limit(1)
        )
        if dataset is None:
            raise NotFoundError("dataset_not_found", "Import a dataset before creating requests")
        existing_event = await self._session.scalar(
            select(DayEventRow).where(
                DayEventRow.scenario_id == scenario_id,
                DayEventRow.idempotency_key == idempotency_key,
            )
        )
        if existing_event is not None:
            existing_id = cast(str, existing_event.payload.get("request_id"))
            return {"request_id": UUID(existing_id), "event_id": existing_event.id, "duplicate": True}
        duplicate = await self._session.scalar(
            select(RequestRow).where(
                RequestRow.dataset_id == dataset.id, RequestRow.external_id == external_id
            )
        )
        if duplicate is not None:
            raise ConflictError("duplicate_request", "Request external ID already exists")
        if await self._session.get(SkillRow, required_skill) is None:
            raise DomainError("unknown_skill", "Required skill is not in the reference data")
        if required_transport and await self._session.get(TransportTypeRow, required_transport) is None:
            raise DomainError("unknown_transport", "Required transport is not in the reference data")
        location = await self._get_or_create_location(address, "Москва")
        now = self._now()
        request = RequestRow(
            scenario_id=scenario_id,
            dataset_id=dataset.id,
            location_id=location.id,
            external_id=external_id,
            planning_date=planning_date,
            bk_type="API",
            hd_type="API",
            district=district,
            window_start=_as_utc(window_start),
            window_end=_as_utc(window_end),
            work_type_id=None,
            service_minutes=service_minutes,
            full_normative_minutes=service_minutes,
            required_skill_code=required_skill,
            required_transport_code=required_transport,
            priority=priority,
            mapping_state="mapped",
            gigabit=False,
            connection_kind=None,
            version=1,
            created_at=now,
        )
        self._session.add(request)
        await self._session.flush()
        self._session.add(
            RequestStatusEventRow(
                request_id=request.id,
                status=RequestStatus.NOT_SENT.value,
                source="api",
                actor=actor,
                effective_at=now,
                recorded_at=now,
                actual_start=None,
                actual_finish=None,
                reason="Request created by dispatcher",
                corrects_event_id=None,
                idempotency_key=f"new-request:{idempotency_key}",
            )
        )
        event = DayEventRow(
            scenario_id=scenario_id,
            planning_date=planning_date,
            event_type="new_request",
            effective_at=now,
            recorded_at=now,
            actor=actor,
            idempotency_key=idempotency_key,
            payload={"request_id": str(request.id)},
            processing_state="queued",
        )
        self._session.add(event)
        await self._session.flush()
        self._session.add(
            OutboxJobRow(
                job_type="replan",
                status="queued",
                idempotency_key=f"new-request:{scenario_id}:{idempotency_key}",
                payload={"request_id": str(request.id), "scenario_id": str(scenario_id)},
                available_at=now,
                attempts=0,
                last_error=None,
            )
        )
        await self._audit(
            scenario_id,
            "request_created",
            "request",
            request.id,
            actor,
            details={"event_id": str(event.id)},
        )
        await self._session.commit()
        return {"request_id": request.id, "event_id": event.id, "duplicate": False}

    async def build_snapshot(
        self, scenario_id: UUID, planning_date: date, as_of: datetime, base_plan_id: UUID | None
    ) -> PlanningSnapshot:
        scenario = await self._session.get(ScenarioRow, scenario_id)
        if scenario is None or scenario.office_location_id is None:
            raise NotFoundError("scenario_not_found", "Scenario not found")
        dataset = await self._session.scalar(
            select(DatasetRow)
            .where(
                DatasetRow.scenario_id == scenario_id, DatasetRow.planning_date == planning_date
            )
            .order_by(DatasetRow.imported_at.desc())
            .limit(1)
        )
        if dataset is None:
            raise NotFoundError("dataset_not_found", "No dataset for scenario and date")
        requests = (
            await self._session.scalars(
                select(RequestRow)
                .where(RequestRow.dataset_id == dataset.id)
                .order_by(RequestRow.window_start, RequestRow.external_id)
            )
        ).all()
        statuses = await self._latest_statuses([item.id for item in requests])
        location_ids = list(dict.fromkeys([scenario.office_location_id, *[item.location_id for item in requests]]))
        locations = (
            await self._session.scalars(select(LocationRow).where(LocationRow.id.in_(location_ids)))
        ).all()
        location_by_id = {item.id: item for item in locations}
        if any(
            location_by_id[item].latitude is None or location_by_id[item].longitude is None
            for item in location_ids
        ):
            raise DomainError("geocoding_required", "One or more locations have no coordinates")
        engineers = (
            await self._session.scalars(
                select(EngineerRow).where(
                    EngineerRow.scenario_id == scenario_id, EngineerRow.active.is_(True)
                ).order_by(EngineerRow.external_code)
            )
        ).all()
        engineer_data: list[EngineerData] = []
        for engineer in engineers:
            shift = await self._session.scalar(
                select(ShiftRow).where(
                    ShiftRow.engineer_id == engineer.id,
                    ShiftRow.shift_date == planning_date,
                    ShiftRow.available.is_(True),
                )
            )
            if shift is None:
                continue
            skills = set(
                (
                    await self._session.scalars(
                        select(EngineerSkillRow.skill_code).where(
                            EngineerSkillRow.engineer_id == engineer.id
                        )
                    )
                ).all()
            )
            shift_start = datetime.combine(planning_date, shift.start_time, self._timezone)
            shift_end = datetime.combine(planning_date, shift.end_time, self._timezone)
            engineer_data.append(
                EngineerData(
                    id=engineer.id,
                    name=engineer.name,
                    office_location_id=engineer.home_location_id,
                    shift_start=shift_start,
                    shift_end=shift_end,
                    skills=skills,
                    transport=engineer.transport_code,
                    available_from=shift_start,
                    available_location_id=engineer.home_location_id,
                )
            )
        locked: list[LockedAssignmentData] = []
        if base_plan_id is not None:
            base = await self._session.get(PlanRow, base_plan_id)
            if base is None:
                raise NotFoundError("base_plan_not_found", "Base plan not found")
            assignments = (
                await self._session.scalars(
                    select(AssignmentRow).where(AssignmentRow.plan_id == base_plan_id)
                )
            ).all()
            for assignment in assignments:
                status = statuses.get(assignment.request_id)
                if status and status.status in {RequestStatus.EN_ROUTE.value, RequestStatus.IN_PROGRESS.value}:
                    locked.append(
                        LockedAssignmentData(
                            request_id=assignment.request_id,
                            engineer_id=assignment.engineer_id,
                            position=assignment.position,
                            location_id=assignment.location_id,
                            start_at=_with_zone(assignment.start_at, self._timezone),
                            finish_at=_with_zone(assignment.finish_at, self._timezone),
                        )
                    )
        events = (
            await self._session.scalars(
                select(DayEventRow)
                .where(
                    DayEventRow.scenario_id == scenario_id,
                    DayEventRow.planning_date == planning_date,
                    DayEventRow.effective_at <= _as_utc(as_of),
                )
                .order_by(DayEventRow.effective_at)
            )
        ).all()
        version_payload = {
            "dataset": str(dataset.id),
            "base": str(base_plan_id) if base_plan_id else None,
            "events": [str(item.id) for item in events],
            "facts": [str(statuses[item.id].id) for item in requests],
            "requests": [str(item.id) for item in requests],
        }
        input_version = hashlib.sha256(
            json.dumps(version_payload, sort_keys=True).encode()
        ).hexdigest()
        return PlanningSnapshot(
            input_version=input_version,
            dataset_id=dataset.id,
            base_plan_id=base_plan_id,
            scenario_id=scenario_id,
            planning_date=planning_date,
            timezone=scenario.timezone,
            as_of=as_of,
            locations=[
                LocationData(
                    id=location_by_id[item].id,
                    address=location_by_id[item].address,
                    latitude=cast(float, location_by_id[item].latitude),
                    longitude=cast(float, location_by_id[item].longitude),
                )
                for item in location_ids
            ],
            location_ids=location_ids,
            travel_by_profile={},
            requests=[
                RequestData(
                    id=item.id,
                    external_id=item.external_id,
                    location_id=item.location_id,
                    window_start=_with_zone(item.window_start, self._timezone),
                    window_end=_with_zone(item.window_end, self._timezone),
                    service_minutes=item.service_minutes,
                    full_normative_minutes=item.full_normative_minutes,
                    required_skill=item.required_skill_code,
                    required_transport=item.required_transport_code,
                    priority=item.priority,
                    status=statuses[item.id].status,
                    mapping_state=item.mapping_state,
                )
                for item in requests
            ],
            engineers=engineer_data,
            locked_assignments=locked,
            execution_snapshot={
                "confirmed_status_event_ids": [str(statuses[item.id].id) for item in requests]
            },
            events=[
                {
                    "id": str(item.id),
                    "event_type": item.event_type,
                    "effective_at": item.effective_at.isoformat(),
                    "payload": item.payload,
                }
                for item in events
            ],
            policies={
                "window_requires_full_completion": True,
                "return_to_office": False,
                "travel_unit": "seconds",
                "distance_unit": "meters",
            },
        )

    async def attach_matrix(
        self, snapshot: PlanningSnapshot, matrix: RouteMatrix
    ) -> PlanningSnapshot:
        travel = TravelSnapshot.model_validate(matrix.model_dump())
        return snapshot.model_copy(update={"travel_by_profile": {matrix.profile: travel}})

    async def start_run(self, snapshot: PlanningSnapshot, algorithm: str) -> UUID:
        now = self._now()
        run = PlanningRunRow(
            scenario_id=snapshot.scenario_id,
            dataset_id=snapshot.dataset_id,
            planning_date=snapshot.planning_date,
            base_plan_id=snapshot.base_plan_id,
            status="running",
            algorithm=algorithm,
            input_version=snapshot.input_version,
            started_at=now,
            finished_at=None,
            failure_code=None,
            failure_message=None,
            diagnostics={},
        )
        self._session.add(run)
        await self._session.commit()
        return run.id

    async def save_candidate(
        self,
        run_id: UUID,
        snapshot: PlanningSnapshot,
        candidate: PlanCandidate,
        algorithm: str,
        route_geometries: dict[UUID, dict[str, object]],
    ) -> tuple[UUID, UUID]:
        validate_candidate(snapshot, candidate)
        now = self._now()
        run = await self._session.get(PlanningRunRow, run_id)
        if run is None:
            raise NotFoundError("planning_run_not_found", "Planning run not found")
        if run.status != "running":
            raise ConflictError("planning_run_not_running", "Planning run is not running")
        plan = PlanRow(
            scenario_id=snapshot.scenario_id,
            dataset_id=snapshot.dataset_id,
            planning_run_id=run_id,
            planning_date=snapshot.planning_date,
            parent_plan_id=snapshot.base_plan_id,
            base_plan_id=snapshot.base_plan_id,
            status="draft",
            approved_slot=None,
            schema_version=snapshot.schema_version,
            input_version=snapshot.input_version,
            input_snapshot=snapshot.model_dump(mode="json"),
            warnings=list(candidate.warnings),
            version=1,
            created_at=now,
        )
        self._session.add(plan)
        await self._session.flush()
        for item in candidate.assignments:
            self._session.add(
                AssignmentRow(
                    plan_id=plan.id,
                    request_id=item.request_id,
                    engineer_id=item.engineer_id,
                    position=item.position,
                    from_location_id=item.from_location_id,
                    location_id=item.location_id,
                    arrival_at=_as_utc(item.arrival_at),
                    start_at=_as_utc(item.start_at),
                    finish_at=_as_utc(item.finish_at),
                    travel_seconds=item.travel_seconds,
                    distance_meters=item.distance_meters,
                    explanation=item.explanation,
                )
            )
            self._session.add(
                RouteLegRow(
                    plan_id=plan.id,
                    engineer_id=item.engineer_id,
                    sequence=item.position,
                    from_location_id=item.from_location_id,
                    to_location_id=item.location_id,
                    duration_seconds=item.travel_seconds,
                    distance_meters=item.distance_meters,
                    matrix_snapshot_key=snapshot.input_version,
                    geometry=(
                        route_geometries.get(item.engineer_id) if item.position == 1 else None
                    ),
                )
            )
        for unassigned_item in candidate.unassigned:
            self._session.add(
                UnassignedRequestRow(
                    plan_id=plan.id,
                    request_id=unassigned_item.request_id,
                    reason_code=unassigned_item.reason_code,
                    explanation=unassigned_item.explanation,
                )
            )
        total_requests = len(snapshot.requests)
        assigned = len(candidate.assignments)
        engineers_used = len({item.engineer_id for item in candidate.assignments})
        metrics = {
            "assigned_count": (float(assigned), "count"),
            "unassigned_count": (float(len(candidate.unassigned)), "count"),
            "coverage_ratio": (assigned / total_requests if total_requests else 0.0, "ratio"),
            "engineers_used": (float(engineers_used), "count"),
            "travel_distance_meters": (
                float(sum(item.distance_meters for item in candidate.assignments)),
                "meters",
            ),
            "travel_time_seconds": (
                float(sum(item.travel_seconds for item in candidate.assignments)),
                "seconds",
            ),
            "service_time_minutes": (
                float(
                    sum(
                        int((item.finish_at - item.start_at).total_seconds() / 60)
                        for item in candidate.assignments
                    )
                ),
                "minutes",
            ),
        }
        for code, (value, unit) in metrics.items():
            self._session.add(
                PlanMetricRow(
                    plan_id=plan.id,
                    metric_code=code,
                    numeric_value=value,
                    text_value=None,
                    unit=unit,
                )
            )
        run.status = "succeeded"
        run.finished_at = now
        await self._audit(
            snapshot.scenario_id,
            "plan_calculated",
            "plan",
            plan.id,
            "system",
            details={"run_id": str(run.id), "algorithm": algorithm},
        )
        await self._session.commit()
        return run_id, plan.id

    async def mark_run_failed(self, run_id: UUID, code: str, message: str) -> None:
        row = await self._session.get(PlanningRunRow, run_id)
        if row is None:
            return
        row.status = "failed"
        row.failure_code = code
        row.failure_message = message
        row.finished_at = self._now()
        await self._session.commit()

    async def approve_plan(
        self, plan_id: UUID, expected_base_plan_id: UUID | None, actor: str
    ) -> dict[str, object]:
        plan = await self._session.scalar(
            select(PlanRow).where(PlanRow.id == plan_id).with_for_update()
        )
        if plan is None:
            raise NotFoundError("plan_not_found", "Plan not found")
        if plan.status != "draft":
            raise ConflictError("plan_not_draft", "Only a draft plan can be approved")
        fresh_snapshot = await self.build_snapshot(
            plan.scenario_id,
            plan.planning_date,
            self._now(),
            plan.base_plan_id,
        )
        if fresh_snapshot.input_version != plan.input_version:
            raise ConflictError(
                "stale_input_version",
                "Facts or events changed after this draft was calculated",
                {
                    "draft_input_version": plan.input_version,
                    "current_input_version": fresh_snapshot.input_version,
                },
            )
        active = await self._session.scalar(
            select(PlanRow)
            .where(
                PlanRow.scenario_id == plan.scenario_id,
                PlanRow.planning_date == plan.planning_date,
                PlanRow.approved_slot.is_(True),
            )
            .with_for_update()
        )
        active_id = active.id if active else None
        if plan.base_plan_id != active_id or expected_base_plan_id != plan.base_plan_id:
            raise ConflictError(
                "stale_base_plan",
                "Draft was calculated from a plan that is no longer active",
                {
                    "draft_base_plan_id": str(plan.base_plan_id) if plan.base_plan_id else None,
                    "active_plan_id": str(active_id) if active_id else None,
                },
            )
        if active is not None:
            active.status = "superseded"
            active.approved_slot = None
            active.version += 1
            await self._session.flush()
        plan.status = "approved"
        plan.approved_slot = True
        plan.version += 1
        now = self._now()
        self._session.add(
            PlanApprovalRow(
                plan_id=plan.id, actor=actor, approved_at=now, base_plan_id=plan.base_plan_id
            )
        )
        await self._audit(
            plan.scenario_id,
            "plan_approved",
            "plan",
            plan.id,
            actor,
            details={"superseded_plan_id": str(active_id) if active_id else None},
        )
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError("concurrent_approval", "Another plan was approved concurrently") from exc
        return {"plan_id": plan.id, "status": plan.status, "approved_at": now}

    async def list_plans(
        self, scenario_id: UUID, planning_date: date
    ) -> list[dict[str, object]]:
        rows = (
            await self._session.scalars(
                select(PlanRow)
                .where(PlanRow.scenario_id == scenario_id, PlanRow.planning_date == planning_date)
                .order_by(PlanRow.created_at.desc())
            )
        ).all()
        return [
            {
                "id": row.id,
                "status": row.status,
                "parent_plan_id": row.parent_plan_id,
                "base_plan_id": row.base_plan_id,
                "input_version": row.input_version,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def get_plan(self, plan_id: UUID) -> dict[str, object]:
        plan = await self._session.get(PlanRow, plan_id)
        if plan is None:
            raise NotFoundError("plan_not_found", "Plan not found")
        assignment_rows = (
            await self._session.execute(
                select(AssignmentRow, RequestRow, EngineerRow, LocationRow)
                .join(RequestRow, AssignmentRow.request_id == RequestRow.id)
                .join(EngineerRow, AssignmentRow.engineer_id == EngineerRow.id)
                .join(LocationRow, AssignmentRow.location_id == LocationRow.id)
                .where(AssignmentRow.plan_id == plan_id)
                .order_by(EngineerRow.name, AssignmentRow.position)
            )
        ).all()
        unassigned_rows = (
            await self._session.execute(
                select(UnassignedRequestRow, RequestRow)
                .join(RequestRow, UnassignedRequestRow.request_id == RequestRow.id)
                .where(UnassignedRequestRow.plan_id == plan_id)
            )
        ).all()
        metrics = (
            await self._session.scalars(
                select(PlanMetricRow).where(PlanMetricRow.plan_id == plan_id)
            )
        ).all()
        route_rows = (
            await self._session.scalars(
                select(RouteLegRow).where(
                    RouteLegRow.plan_id == plan_id,
                    RouteLegRow.geometry.is_not(None),
                )
            )
        ).all()
        return {
            "id": plan.id,
            "scenario_id": plan.scenario_id,
            "planning_date": plan.planning_date,
            "status": plan.status,
            "parent_plan_id": plan.parent_plan_id,
            "base_plan_id": plan.base_plan_id,
            "input_version": plan.input_version,
            "assignments": [
                {
                    "request_id": assignment.request_id,
                    "request_external_id": request.external_id,
                    "engineer_id": engineer.id,
                    "engineer": engineer.name,
                    "position": assignment.position,
                    "address": location.address,
                    "arrival_at": assignment.arrival_at,
                    "start_at": assignment.start_at,
                    "finish_at": assignment.finish_at,
                    "travel_seconds": assignment.travel_seconds,
                    "distance_meters": assignment.distance_meters,
                    "explanation": assignment.explanation,
                }
                for assignment, request, engineer, location in assignment_rows
            ],
            "unassigned": [
                {
                    "request_id": row.request_id,
                    "request_external_id": request.external_id,
                    "reason_code": row.reason_code,
                    "explanation": row.explanation,
                }
                for row, request in unassigned_rows
            ],
            "metrics": {
                metric.metric_code: metric.numeric_value
                if metric.numeric_value is not None
                else metric.text_value
                for metric in metrics
            },
            "routes": [
                {
                    "engineer_id": route.engineer_id,
                    "profile": "driving",
                    "geometry": route.geometry,
                }
                for route in route_rows
                if route.geometry is not None
            ],
            "warnings": plan.warnings,
        }

    async def get_run(self, run_id: UUID) -> dict[str, object]:
        row = await self._session.get(PlanningRunRow, run_id)
        if row is None:
            raise NotFoundError("planning_run_not_found", "Planning run not found")
        plan_id = await self._session.scalar(
            select(PlanRow.id).where(PlanRow.planning_run_id == row.id)
        )
        return {
            "id": row.id,
            "status": row.status,
            "algorithm": row.algorithm,
            "input_version": row.input_version,
            "plan_id": plan_id,
            "failure": (
                {"code": row.failure_code, "message": row.failure_message}
                if row.failure_code
                else None
            ),
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        }

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
        request = await self._session.get(RequestRow, request_id)
        if request is None:
            raise NotFoundError("request_not_found", "Request not found")
        latest = await self._session.scalar(
            select(RequestStatusEventRow)
            .where(RequestStatusEventRow.request_id == request_id)
            .order_by(RequestStatusEventRow.recorded_at.desc())
            .limit(1)
        )
        if latest is not None:
            validate_status_transition(RequestStatus(latest.status), status)
        if actual_start and actual_finish and actual_finish < actual_start:
            raise DomainError("invalid_actual_times", "Actual finish cannot precede actual start")
        event = RequestStatusEventRow(
            request_id=request_id,
            status=status.value,
            source="demo_manual",
            actor=actor,
            effective_at=_as_utc(effective_at),
            recorded_at=self._now(),
            actual_start=_as_utc(actual_start) if actual_start else None,
            actual_finish=_as_utc(actual_finish) if actual_finish else None,
            reason=reason,
            corrects_event_id=latest.id if latest else None,
            idempotency_key=None,
        )
        self._session.add(event)
        await self._audit(
            request.scenario_id,
            "request_fact_recorded",
            "request",
            request.id,
            actor,
            reason,
            {"status": status.value},
        )
        await self._session.commit()
        return {"event_id": event.id, "request_id": request_id, "status": status.value}

    async def create_event(
        self,
        scenario_id: UUID,
        planning_date: date,
        event_type: str,
        effective_at: datetime,
        payload: dict[str, object],
        idempotency_key: str,
        actor: str,
    ) -> dict[str, object]:
        existing = await self._session.scalar(
            select(DayEventRow).where(
                DayEventRow.scenario_id == scenario_id,
                DayEventRow.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return {"event_id": existing.id, "duplicate": True}
        now = self._now()
        if event_type == "request_cancelled":
            raw_request_id = payload.get("request_id")
            if not isinstance(raw_request_id, str):
                raise DomainError(
                    "missing_event_target", "request_cancelled requires payload.request_id"
                )
            request_id = UUID(raw_request_id)
            request = await self._session.get(RequestRow, request_id)
            if request is None or request.scenario_id != scenario_id:
                raise NotFoundError("request_not_found", "Event request was not found")
            latest = await self._session.scalar(
                select(RequestStatusEventRow)
                .where(RequestStatusEventRow.request_id == request_id)
                .order_by(RequestStatusEventRow.recorded_at.desc())
                .limit(1)
            )
            if latest is not None:
                validate_status_transition(
                    RequestStatus(latest.status), RequestStatus.CANCELLED
                )
            self._session.add(
                RequestStatusEventRow(
                    request_id=request_id,
                    status=RequestStatus.CANCELLED.value,
                    source="demo_manual",
                    actor=actor,
                    effective_at=_as_utc(effective_at),
                    recorded_at=now,
                    actual_start=None,
                    actual_finish=None,
                    reason="Request cancelled by day event",
                    corrects_event_id=latest.id if latest else None,
                    idempotency_key=f"event:{scenario_id}:{idempotency_key}:cancel",
                )
            )
        elif event_type == "engineer_unavailable":
            raw_engineer_id = payload.get("engineer_id")
            if not isinstance(raw_engineer_id, str):
                raise DomainError(
                    "missing_event_target", "engineer_unavailable requires payload.engineer_id"
                )
            engineer_id = UUID(raw_engineer_id)
            engineer = await self._session.get(EngineerRow, engineer_id)
            if engineer is None or engineer.scenario_id != scenario_id:
                raise NotFoundError("engineer_not_found", "Event engineer was not found")
            shift = await self._session.scalar(
                select(ShiftRow).where(
                    ShiftRow.engineer_id == engineer_id,
                    ShiftRow.shift_date == planning_date,
                )
            )
            if shift is None:
                raise NotFoundError("shift_not_found", "Engineer shift was not found")
            shift.available = False
            engineer.version += 1
        elif event_type == "urgent_request":
            raw_request_id = payload.get("request_id")
            if not isinstance(raw_request_id, str):
                raise DomainError(
                    "missing_event_target",
                    "urgent_request requires an existing payload.request_id; create new work via POST /requests",
                )
            request_id = UUID(raw_request_id)
            request = await self._session.get(RequestRow, request_id)
            if request is None or request.scenario_id != scenario_id:
                raise NotFoundError("request_not_found", "Urgent request was not found")
            request.priority = "urgent"
            request.version += 1
        event = DayEventRow(
            scenario_id=scenario_id,
            planning_date=planning_date,
            event_type=event_type,
            effective_at=_as_utc(effective_at),
            recorded_at=now,
            actor=actor,
            idempotency_key=idempotency_key,
            payload=payload,
            processing_state="queued",
        )
        self._session.add(event)
        await self._session.flush()
        job = OutboxJobRow(
            job_type="replan",
            status="queued",
            idempotency_key=f"event:{scenario_id}:{idempotency_key}",
            payload={"event_id": str(event.id), "scenario_id": str(scenario_id)},
            available_at=now,
            attempts=0,
            last_error=None,
        )
        self._session.add(job)
        await self._audit(
            scenario_id,
            "day_event_created",
            "event",
            event.id,
            actor,
            details={"event_type": event_type},
        )
        await self._session.commit()
        return {"event_id": event.id, "duplicate": False}

    async def diff_plans(self, old_plan_id: UUID, new_plan_id: UUID) -> dict[str, object]:
        old = await self._session.get(PlanRow, old_plan_id)
        new = await self._session.get(PlanRow, new_plan_id)
        if old is None or new is None:
            raise NotFoundError("plan_not_found", "One of the plans was not found")
        if (old.scenario_id, old.planning_date) != (new.scenario_id, new.planning_date):
            raise DomainError("incomparable_plans", "Plans must belong to the same scenario and date")
        async def assignments(plan_id: UUID) -> dict[UUID, AssignmentRow]:
            rows = (
                await self._session.scalars(
                    select(AssignmentRow).where(AssignmentRow.plan_id == plan_id)
                )
            ).all()
            return {row.request_id: row for row in rows}

        old_assignments = await assignments(old_plan_id)
        new_assignments = await assignments(new_plan_id)
        request_ids = set(old_assignments) | set(new_assignments)
        changes: list[dict[str, object]] = []
        counters: defaultdict[str, int] = defaultdict(int)
        for request_id in sorted(request_ids, key=str):
            before = old_assignments.get(request_id)
            after = new_assignments.get(request_id)
            flags: list[str] = []
            if before is None:
                flags.append("added")
            elif after is None:
                flags.append("removed")
            else:
                if before.engineer_id != after.engineer_id:
                    flags.append("reassigned")
                if before.position != after.position:
                    flags.append("reordered")
                if before.start_at != after.start_at or before.finish_at != after.finish_at:
                    flags.append("rescheduled")
                if (
                    before.distance_meters != after.distance_meters
                    or before.from_location_id != after.from_location_id
                ):
                    flags.append("route_changed")
            if not flags:
                flags.append("unchanged")
            for flag in flags:
                counters[flag] += 1
            changes.append(
                {
                    "request_id": request_id,
                    "changes": flags,
                    "old": self._assignment_diff_value(before),
                    "new": self._assignment_diff_value(after),
                }
            )
        return {"old_plan_id": old_plan_id, "new_plan_id": new_plan_id, "summary": dict(counters), "items": changes}

    @staticmethod
    def _assignment_diff_value(row: AssignmentRow | None) -> dict[str, object] | None:
        if row is None:
            return None
        return {
            "engineer_id": row.engineer_id,
            "position": row.position,
            "start_at": row.start_at,
            "finish_at": row.finish_at,
            "from_location_id": row.from_location_id,
            "location_id": row.location_id,
            "distance_meters": row.distance_meters,
        }

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
        plan = await self._session.get(PlanRow, plan_id)
        if plan is None:
            raise NotFoundError("plan_not_found", "Plan not found")
        original_snapshot = PlanningSnapshot.model_validate(plan.input_snapshot)
        snapshot = await self.build_snapshot(
            plan.scenario_id,
            plan.planning_date,
            self._now(),
            plan_id,
        )
        snapshot = snapshot.model_copy(
            update={"travel_by_profile": original_snapshot.travel_by_profile}
        )
        existing = (
            await self._session.scalars(
                select(AssignmentRow).where(AssignmentRow.plan_id == plan_id)
            )
        ).all()
        unassigned_rows = (
            await self._session.scalars(
                select(UnassignedRequestRow).where(UnassignedRequestRow.plan_id == plan_id)
            )
        ).all()
        if not any(item.request_id == request_id for item in existing):
            raise DomainError("request_not_assigned", "Manual change requires an assigned request")
        request_by_id = {item.id: item for item in snapshot.requests}
        engineer_by_id = {item.id: item for item in snapshot.engineers}
        request = request_by_id.get(request_id)
        target = engineer_by_id.get(engineer_id)
        if request is None or target is None:
            raise DomainError("manual_change_unknown_id", "Request or engineer is not in the snapshot")
        latest_status = await self._session.scalar(
            select(RequestStatusEventRow)
            .where(RequestStatusEventRow.request_id == request_id)
            .order_by(RequestStatusEventRow.recorded_at.desc())
            .limit(1)
        )
        current_status = RequestStatus(latest_status.status) if latest_status else request.status
        if current_status in {RequestStatus.EN_ROUTE, RequestStatus.IN_PROGRESS}:
            raise ConflictError("request_locked", "EN_ROUTE and IN_PROGRESS requests cannot be reassigned")
        if request.required_skill and request.required_skill not in target.skills:
            raise DomainError("missing_skill", "Target engineer lacks the required skill")
        if request.required_transport and request.required_transport != target.transport:
            raise DomainError("missing_transport", "Target engineer lacks the required transport")
        routes: defaultdict[UUID, list[UUID]] = defaultdict(list)
        for item in sorted(existing, key=lambda row: (str(row.engineer_id), row.position)):
            if item.request_id != request_id:
                routes[item.engineer_id].append(item.request_id)
        insert_at = max(0, min(position - 1, len(routes[engineer_id])))
        routes[engineer_id].insert(insert_at, request_id)
        travel = snapshot.travel_by_profile["driving"]
        location_index = {value: idx for idx, value in enumerate(snapshot.location_ids)}
        rebuilt: list[Assignment] = []
        for route_engineer_id, route_requests in routes.items():
            engineer = engineer_by_id[route_engineer_id]
            previous_location = engineer.office_location_id
            previous_finish = engineer.shift_start
            for index, current_request_id in enumerate(route_requests, start=1):
                current = request_by_id[current_request_id]
                cell = travel.cells[location_index[previous_location]][location_index[current.location_id]]
                if cell.duration_seconds is None or cell.distance_meters is None:
                    raise DomainError("unreachable", "Manual route contains an unreachable leg")
                timing = calculate_visit(
                    previous_finish,
                    cell.duration_seconds,
                    VisitWindow(current.window_start, current.window_end),
                    current.service_minutes or 0,
                    engineer.shift_end,
                )
                if current_request_id == request_id and start_at is not None:
                    manual_start = max(start_at, timing.arrival)
                    manual_finish = manual_start + (timing.finish - timing.start)
                    if manual_start < current.window_start or manual_finish > current.window_end:
                        raise DomainError("outside_client_window", "Requested manual time violates the window")
                    if manual_finish > engineer.shift_end:
                        raise DomainError("outside_shift", "Requested manual time violates the shift")
                    timing = type(timing)(timing.arrival, manual_start, manual_finish)
                rebuilt.append(
                    Assignment(
                        request_id=current.id,
                        engineer_id=engineer.id,
                        position=index,
                        from_location_id=previous_location,
                        location_id=current.location_id,
                        arrival_at=timing.arrival,
                        start_at=timing.start,
                        finish_at=timing.finish,
                        travel_seconds=cell.duration_seconds,
                        distance_meters=cell.distance_meters,
                        explanation=f"Manual dispatcher change: {reason}",
                    )
                )
                previous_location = current.location_id
                previous_finish = timing.finish
        candidate = PlanCandidate(
            schema_version=snapshot.schema_version,
            input_version=snapshot.input_version,
            assignments=tuple(rebuilt),
            unassigned=tuple(
                Unassigned(item.request_id, item.reason_code, item.explanation)
                for item in unassigned_rows
            ),
        )
        run_id = await self.start_run(snapshot, "manual-dispatcher-v1")
        _, new_plan_id = await self.save_candidate(
            run_id,
            snapshot,
            candidate,
            "manual-dispatcher-v1",
            {},
        )
        await self._audit(
            plan.scenario_id,
            "manual_plan_change",
            "plan",
            new_plan_id,
            actor,
            reason,
            {"parent_plan_id": str(plan_id), "request_id": str(request_id)},
        )
        await self._session.commit()
        return new_plan_id

    async def build_report(self, plan_id: UUID, now: datetime) -> DayReport:
        plan = await self._session.get(PlanRow, plan_id)
        if plan is None:
            raise NotFoundError("plan_not_found", "Plan not found")
        scenario = await self._session.get(ScenarioRow, plan.scenario_id)
        rows = (
            await self._session.execute(
                select(AssignmentRow, RequestRow, EngineerRow, LocationRow)
                .join(RequestRow, AssignmentRow.request_id == RequestRow.id)
                .join(EngineerRow, AssignmentRow.engineer_id == EngineerRow.id)
                .join(LocationRow, AssignmentRow.location_id == LocationRow.id)
                .where(AssignmentRow.plan_id == plan_id)
                .order_by(EngineerRow.name, AssignmentRow.position)
            )
        ).all()
        statuses = await self._latest_statuses([request.id for _, request, _, _ in rows])
        metrics_rows = (
            await self._session.scalars(
                select(PlanMetricRow).where(PlanMetricRow.plan_id == plan_id)
            )
        ).all()
        return DayReport(
            report_version=plan.input_version[:12],
            plan_id=plan.id,
            scenario=scenario.name if scenario else str(plan.scenario_id),
            planning_date=plan.planning_date,
            generated_at=now,
            interim=now.astimezone(self._timezone).date() <= plan.planning_date,
            assignments=[
                ReportAssignment(
                    engineer=engineer.name,
                    position=assignment.position,
                    request_external_id=request.external_id,
                    address=location.address,
                    planned_start=assignment.start_at,
                    planned_finish=assignment.finish_at,
                    confirmed_status=statuses[request.id].status,
                    actual_start=statuses[request.id].actual_start,
                    actual_finish=statuses[request.id].actual_finish,
                    fact_source=statuses[request.id].source,
                    distance_meters=assignment.distance_meters,
                )
                for assignment, request, engineer, location in rows
            ],
            metrics={
                item.metric_code: item.numeric_value
                if item.numeric_value is not None
                else (item.text_value or "")
                for item in metrics_rows
            },
        )

    async def route_coordinate_sets(
        self, plan_id: UUID
    ) -> dict[UUID, list[tuple[float, float]]]:
        assignments = (
            await self._session.scalars(
                select(AssignmentRow)
                .where(AssignmentRow.plan_id == plan_id)
                .order_by(AssignmentRow.engineer_id, AssignmentRow.position)
            )
        ).all()
        result: dict[UUID, list[tuple[float, float]]] = {}
        for assignment in assignments:
            if assignment.engineer_id not in result:
                origin = await self._session.get(LocationRow, assignment.from_location_id)
                if origin is None or origin.latitude is None or origin.longitude is None:
                    raise DomainError("geocoding_required", "Route origin has no coordinates")
                result[assignment.engineer_id] = [(origin.latitude, origin.longitude)]
            destination = await self._session.get(LocationRow, assignment.location_id)
            if destination is None or destination.latitude is None or destination.longitude is None:
                raise DomainError("geocoding_required", "Route destination has no coordinates")
            result[assignment.engineer_id].append(
                (destination.latitude, destination.longitude)
            )
        return result

    async def store_route_geometries(
        self, plan_id: UUID, geometries: dict[UUID, dict[str, object]]
    ) -> None:
        for engineer_id, geometry in geometries.items():
            first_leg = await self._session.scalar(
                select(RouteLegRow).where(
                    RouteLegRow.plan_id == plan_id,
                    RouteLegRow.engineer_id == engineer_id,
                    RouteLegRow.sequence == 1,
                )
            )
            if first_leg is not None:
                first_leg.geometry = geometry
        await self._session.commit()

    async def get_audit(
        self, scenario_id: UUID, limit: int, offset: int
    ) -> list[dict[str, object]]:
        rows = (
            await self._session.scalars(
                select(AuditLogRow)
                .where(AuditLogRow.scenario_id == scenario_id)
                .order_by(AuditLogRow.recorded_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [
            {
                "id": row.id,
                "action": row.action,
                "actor": row.actor,
                "source": row.source,
                "effective_at": row.effective_at,
                "recorded_at": row.recorded_at,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "reason": row.reason,
                "details": row.details,
            }
            for row in rows
        ]
