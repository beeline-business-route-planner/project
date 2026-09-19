from __future__ import annotations

import contextvars
import json
import logging
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, File, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.background import BackgroundTask

from beeline_backend.application.planner import DeterministicPlanningAlgorithm
from beeline_backend.application.ports import ReportRenderer
from beeline_backend.application.routing import DetailedResponse, OverviewResponse, RouteBuilder
from beeline_backend.application.services import BackendService
from beeline_backend.config import Settings, get_settings
from beeline_backend.domain.errors import (
    ConflictError,
    DependencyUnavailableError,
    DomainError,
    NotFoundError,
)
from beeline_backend.infrastructure.clock import SystemClock
from beeline_backend.infrastructure.db import create_engine, create_session_factory
from beeline_backend.infrastructure.gateway import SqlGateway
from beeline_backend.infrastructure.importer import XlsxDatasetImporter
from beeline_backend.infrastructure.logging import JsonFormatter
from beeline_backend.infrastructure.models import Base
from beeline_backend.infrastructure.providers import (
    DemoGeocoder,
    DemoRoutingProvider,
    DgisGeocoder,
    DgisRoutingProvider,
    HybridRoutingProvider,
    MissingGeocoder,
    NominatimGeocoder,
    OsrmRoutingProvider,
    YandexRoutingProvider,
)
from beeline_backend.infrastructure.reports import PdfReportRenderer, XlsxReportRenderer
from beeline_backend.infrastructure.route_store import (
    DragonflyRouteCache,
    RouteReader,
    SqlSegmentStore,
)
from beeline_backend.presentation.dto import (
    ApprovalRequest,
    ApprovalResponse,
    AuditResponse,
    DashboardResponse,
    DayEventRequest,
    DayEventResponse,
    EngineerResponse,
    EngineerRouteResponse,
    ErrorBody,
    FactRequest,
    FactResponse,
    ImportResponse,
    ManualChangeRequest,
    ManualChangeResponse,
    NewRequest,
    NewRequestResponse,
    PlanChangesResponse,
    PlanDiffResponse,
    PlanMetricsResponse,
    PlanningRequest,
    PlanningResultResponse,
    PlanningRunResponse,
    PlanResponse,
    PlanSummaryResponse,
    ReplanningRequest,
    RequestDetailResponse,
    RequestListItemResponse,
    RequestUpdate,
    RequestUpdateResponse,
    ScenarioResponse,
    StatusResponse,
)

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="unknown"
)
logger = logging.getLogger("beeline_backend")


def _provider_bundle(settings: Settings) -> tuple[object, object, object, object]:
    clock = SystemClock()
    geocoder: object
    if settings.geocoder_mode == "dgis":
        geocoder = DgisGeocoder(
            settings.dgis_catalog_base_url,
            settings.dgis_api_key,
            settings.dgis_timeout_seconds,
        )
    elif settings.geocoder_mode == "nominatim":
        geocoder = NominatimGeocoder(
            settings.nominatim_base_url,
            settings.nominatim_user_agent,
            settings.nominatim_timeout_seconds,
            settings.nominatim_min_interval_seconds,
            settings.nominatim_email,
        )
    elif settings.geocoder_mode == "hybrid":
        # Compatibility alias: real addresses never silently become synthetic points.
        geocoder = NominatimGeocoder(
            settings.nominatim_base_url, settings.nominatim_user_agent,
            settings.nominatim_timeout_seconds, settings.nominatim_min_interval_seconds,
            settings.nominatim_email,
        )
    elif settings.geocoder_mode == "demo":
        geocoder = DemoGeocoder()
    else:
        geocoder = MissingGeocoder()
    router: object
    if settings.routing_provider == "dgis":
        router = DgisRoutingProvider(
            settings.dgis_base_url,
            settings.dgis_api_key,
            settings.dgis_timeout_seconds,
            settings.dgis_matrix_block_size,
            clock,
        )
    elif settings.routing_provider in {"osrm", "hybrid"}:
        fingerprint = settings.osrm_graph_fingerprint
        if settings.osrm_graph_manifest is not None:
            manifest = json.loads(settings.osrm_graph_manifest.read_text())
            manifest_fingerprint = manifest.get("fingerprint")
            if not isinstance(manifest_fingerprint, str) or len(manifest_fingerprint) != 64:
                raise ValueError("OSRM manifest must contain its graph fingerprint")
            if fingerprint is not None and fingerprint != manifest_fingerprint:
                raise ValueError("OSRM manifest and configured fingerprint do not match")
            fingerprint = manifest_fingerprint
        if fingerprint is None:
            raise ValueError("Local routing requires OSRM_GRAPH_MANIFEST or OSRM_GRAPH_FINGERPRINT")
        osrm = OsrmRoutingProvider(
            settings.osrm_base_url, settings.osrm_timeout_seconds,
            settings.osrm_max_coordinates, clock,
            max_concurrency=settings.osrm_max_concurrency,
            graph_fingerprint=fingerprint,
        )
        router = HybridRoutingProvider(osrm) if settings.routing_provider == "hybrid" else osrm
    elif settings.routing_provider == "yandex":
        router = YandexRoutingProvider(settings.yandex_api_key)
    else:
        router = DemoRoutingProvider(clock)
    return clock, geocoder, router, DeterministicPlanningAlgorithm()


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    logging.basicConfig(
        level=app_settings.log_level,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(app_settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.settings = app_settings
        app.state.providers = _provider_bundle(app_settings)
        if app_settings.app_env == "test":
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        _, _, routing_provider, _ = app.state.providers
        app.state.route_cache = DragonflyRouteCache(
            app_settings.dragonfly_url,
            app_settings.dragonfly_route_ttl_seconds,
            app_settings.dragonfly_timeout_seconds,
        )
        app.state.route_builder = RouteBuilder(routing_provider, SqlSegmentStore(app.state.session_factory),
                                               app_settings.route_overview_tolerance_meters, app_settings.osrm_max_concurrency)
        app.state.route_reader = RouteReader(app.state.session_factory, app.state.route_cache)
        try:
            yield
        finally:
            await app.state.route_builder.aclose()
            await app.state.route_cache.aclose()
            close = getattr(routing_provider, "aclose", None)
            if close is not None:
                await close()
            await engine.dispose()

    app = FastAPI(
        title="Beeline Business Planning Backend",
        version="1.0.0",
        description=(
            "API dispatcher prototype: datasets, requests, engineers, versioned plans, "
            "events, routes, reports and the frontend dashboard."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=app_settings.cors_allow_credentials,
        allow_methods=app_settings.cors_allow_methods,
        allow_headers=app_settings.cors_allow_headers,
        expose_headers=app_settings.cors_expose_headers,
        max_age=app_settings.cors_max_age,
    )

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next: object) -> object:
        started = perf_counter()
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)  # type: ignore[operator]
            response.headers["X-Correlation-ID"] = correlation_id
            logger.info("http_request", extra={"fields": {"method": request.method, "path": request.url.path,
                        "status_code": response.status_code, "correlation_id": correlation_id,
                        "elapsed_ms": round((perf_counter()-started)*1000, 3)}})
            return response
        finally:
            correlation_id_var.reset(token)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        status_code = 422
        if isinstance(exc, NotFoundError):
            status_code = 404
        elif isinstance(exc, ConflictError):
            status_code = 409
        elif isinstance(exc, DependencyUnavailableError):
            status_code = 503
        logger.warning(
            "domain_error correlation_id=%s code=%s path=%s",
            correlation_id_var.get(),
            exc.code,
            request.url.path,
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "correlation_id": correlation_id_var.get(),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Request validation failed",
                "details": {"errors": errors},
                "correlation_id": correlation_id_var.get(),
            },
        )

    app.include_router(_router())
    return app


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def _service(request: Request, session: AsyncSession = Depends(_session)) -> BackendService:
    settings: Settings = request.app.state.settings
    clock, geocoder, router, planner = request.app.state.providers
    gateway = SqlGateway(session, clock, geocoder, settings.business_timezone)
    return BackendService(
        gateway,
        XlsxDatasetImporter(settings.business_timezone),
        router,
        planner,
        clock,
        request.app.state.route_builder,
        request.app.state.route_reader.warm,
    )


def _remove_file(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def _router() -> APIRouter:
    router = APIRouter(
        prefix="/api/v1",
        responses={
            404: {"model": ErrorBody, "description": "Resource not found"},
            409: {"model": ErrorBody, "description": "Version or state conflict"},
            422: {"model": ErrorBody, "description": "Validation or domain error"},
            503: {"model": ErrorBody, "description": "External dependency unavailable"},
        },
    )

    @router.get("/health", response_model=StatusResponse, tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readiness", response_model=StatusResponse, tags=["system"])
    async def readiness(session: AsyncSession = Depends(_session)) -> dict[str, str]:
        await session.execute(select(1))
        return {"status": "ready"}

    @router.get("/plans/{plan_id}/routes", response_model=OverviewResponse, tags=["routes"])
    async def overview_routes(plan_id: UUID, request: Request) -> OverviewResponse:
        reader: RouteReader = request.app.state.route_reader
        return await reader.overview(plan_id)

    @router.get("/plans/{plan_id}/engineers/{engineer_id}/route", response_model=DetailedResponse, tags=["routes"])
    async def detailed_route(plan_id: UUID, engineer_id: UUID, request: Request) -> DetailedResponse:
        reader: RouteReader = request.app.state.route_reader
        return await reader.detailed(plan_id, engineer_id)

    @router.post("/imports", response_model=ImportResponse, tags=["datasets"])
    async def import_dataset(
        request: Request,
        file: UploadFile = File(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        settings: Settings = request.app.state.settings
        content = await file.read(settings.upload_max_bytes + 1)
        if len(content) > settings.upload_max_bytes:
            raise DomainError(
                "upload_too_large",
                "Uploaded file exceeds the configured size limit",
                {"limit_bytes": settings.upload_max_bytes},
            )
        return await service.import_dataset(file.filename or "", content, idempotency_key)

    @router.get("/scenarios", response_model=list[ScenarioResponse], tags=["datasets"])
    async def scenarios(service: BackendService = Depends(_service)) -> list[dict[str, object]]:
        return await service.gateway.list_scenarios()

    @router.get("/requests", response_model=list[RequestListItemResponse], tags=["requests"])
    async def requests(
        scenario_id: UUID,
        planning_date: date,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        service: BackendService = Depends(_service),
    ) -> list[dict[str, object]]:
        return await service.gateway.list_requests(
            scenario_id, planning_date, limit, offset
        )

    @router.get(
        "/requests/{request_id}", response_model=RequestDetailResponse, tags=["requests"]
    )
    async def request_card(
        request_id: UUID, service: BackendService = Depends(_service)
    ) -> dict[str, object]:
        return await service.gateway.get_request(request_id)

    @router.post("/requests", response_model=NewRequestResponse, tags=["requests"])
    async def create_request(
        payload: NewRequest, service: BackendService = Depends(_service)
    ) -> dict[str, object]:
        return await service.create_request(**payload.model_dump())

    @router.patch(
        "/requests/{request_id}", response_model=RequestUpdateResponse, tags=["requests"]
    )
    async def update_request(
        request_id: UUID,
        payload: RequestUpdate,
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        values = payload.model_dump(exclude_unset=True)
        idempotency_key = cast(str, values.pop("idempotency_key"))
        actor = cast(str, values.pop("actor"))
        return await service.update_request(
            request_id, values, idempotency_key, actor
        )

    @router.post(
        "/requests/{request_id}/facts", response_model=FactResponse, tags=["requests"]
    )
    async def record_fact(
        request_id: UUID,
        payload: FactRequest,
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        return await service.record_fact(request_id=request_id, **payload.model_dump())

    @router.get("/engineers", response_model=list[EngineerResponse], tags=["engineers"])
    async def engineers(
        scenario_id: UUID,
        planning_date: date | None = None,
        service: BackendService = Depends(_service),
    ) -> list[dict[str, object]]:
        return await service.gateway.list_engineers(scenario_id, planning_date)

    @router.get(
        "/engineers/{engineer_id}/route",
        response_model=EngineerRouteResponse,
        tags=["engineers"],
    )
    async def engineer_route(
        engineer_id: UUID,
        plan_id: UUID,
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        plan = await service.gateway.get_plan(plan_id)
        plan_assignments = cast(list[dict[str, object]], plan["assignments"])
        assignments = [
            item for item in plan_assignments if item["engineer_id"] == engineer_id
        ]
        plan_routes = cast(list[dict[str, object]], plan["routes"])
        route = next(
            (item for item in plan_routes if item["engineer_id"] == engineer_id),
            None,
        )
        return {
            "plan_id": plan_id,
            "engineer_id": engineer_id,
            "stops": assignments,
            "route": route,
            "assigned_requests_count": len(assignments),
            "workload_seconds": sum(
                int(
                    (
                        cast(datetime, item["finish_at"])
                        - cast(datetime, item["start_at"])
                    ).total_seconds()
                )
                + cast(int, item["travel_seconds"])
                for item in assignments
            ),
            "route_distance_meters": sum(
                cast(int, item["distance_meters"]) for item in assignments
            ),
            "route_duration_seconds": sum(
                cast(int, item["travel_seconds"])
                + int(
                    (
                        cast(datetime, item["finish_at"])
                        - cast(datetime, item["start_at"])
                    ).total_seconds()
                )
                for item in assignments
            ),
            "sla_violations": sum(
                1
                for violation in cast(list[dict[str, object]], plan["violations"])
                if violation["type"] == "SLA_VIOLATION"
                and violation["request_id"]
                in {item["request_id"] for item in assignments}
            ),
        }

    @router.post("/plans/run", response_model=PlanningResultResponse, tags=["plans"])
    async def run_plan(
        payload: PlanningRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        return await service.run_plan(
            **payload.model_dump(), idempotency_key=idempotency_key
        )

    @router.post("/plans/replan", response_model=PlanningResultResponse, tags=["plans"])
    async def replan(
        payload: ReplanningRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        return await service.run_plan(
            **payload.model_dump(), idempotency_key=idempotency_key
        )

    @router.get(
        "/planning-runs/{run_id}", response_model=PlanningRunResponse, tags=["plans"]
    )
    async def planning_run(
        run_id: UUID, service: BackendService = Depends(_service)
    ) -> dict[str, object]:
        return await service.gateway.get_run(run_id)

    @router.get("/plans", response_model=list[PlanSummaryResponse], tags=["plans"])
    async def plans(
        scenario_id: UUID,
        planning_date: date,
        service: BackendService = Depends(_service),
    ) -> list[dict[str, object]]:
        return await service.gateway.list_plans(scenario_id, planning_date)

    @router.get("/plans/diff", response_model=PlanDiffResponse, tags=["plans"])
    async def plan_diff(
        old_plan_id: UUID,
        new_plan_id: UUID,
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        return await service.gateway.diff_plans(old_plan_id, new_plan_id)

    @router.get(
        "/plans/{new_plan_id}/changes", response_model=PlanChangesResponse, tags=["plans"]
    )
    async def plan_changes(
        new_plan_id: UUID, service: BackendService = Depends(_service)
    ) -> dict[str, object]:
        return await service.gateway.get_plan_changes(new_plan_id)

    @router.get("/plans/{plan_id}", response_model=PlanResponse, tags=["plans"])
    async def plan(plan_id: UUID, service: BackendService = Depends(_service)) -> dict[str, object]:
        return await service.gateway.get_plan(plan_id)

    @router.post(
        "/plans/{plan_id}/approve", response_model=ApprovalResponse, tags=["plans"]
    )
    async def approve_plan(
        plan_id: UUID,
        payload: ApprovalRequest,
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        return await service.gateway.approve_plan(
            plan_id, payload.expected_base_plan_id, payload.actor
        )

    @router.post("/events", response_model=DayEventResponse, tags=["events"])
    async def create_event(
        payload: DayEventRequest, service: BackendService = Depends(_service)
    ) -> dict[str, object]:
        return await service.create_event_and_replan(**payload.model_dump())

    @router.post(
        "/plans/{plan_id}/manual-change",
        response_model=ManualChangeResponse,
        tags=["plans"],
    )
    async def manual_change(
        plan_id: UUID,
        payload: ManualChangeRequest,
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        new_plan_id = await service.manual_change(plan_id=plan_id, **payload.model_dump())
        return {"plan_id": new_plan_id, "status": "draft", "parent_plan_id": plan_id}

    @router.get(
        "/plans/{plan_id}/metrics", response_model=PlanMetricsResponse, tags=["plans"]
    )
    async def plan_metrics(
        plan_id: UUID, service: BackendService = Depends(_service)
    ) -> dict[str, object]:
        plan = await service.gateway.get_plan(plan_id)
        return {"plan_id": plan_id, "metrics": plan["metrics"], "unassigned": plan["unassigned"]}

    @router.get("/audit", response_model=list[AuditResponse], tags=["audit"])
    async def audit(
        scenario_id: UUID,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        service: BackendService = Depends(_service),
    ) -> list[dict[str, object]]:
        return await service.gateway.get_audit(scenario_id, limit, offset)

    @router.get("/dashboard", response_model=DashboardResponse, tags=["frontend"])
    async def dashboard(
        scenario_id: UUID,
        planning_date: date,
        service: BackendService = Depends(_service),
    ) -> dict[str, object]:
        plans = await service.gateway.list_plans(scenario_id, planning_date)
        active = next((item for item in plans if item["status"] == "approved"), None)
        return {
            "scenario_id": scenario_id,
            "planning_date": planning_date,
            "active_plan": await service.gateway.get_plan(active["id"]) if active else None,  # type: ignore[arg-type]
            "requests": await service.gateway.list_requests(scenario_id, planning_date, 500, 0),
            "engineers": await service.gateway.list_engineers(scenario_id),
        }

    @router.get("/plans/{plan_id}/reports/{report_format}", tags=["reports"])
    async def report(
        plan_id: UUID,
        report_format: str,
        service: BackendService = Depends(_service),
    ) -> FileResponse:
        if report_format == "xlsx":
            renderer: ReportRenderer = XlsxReportRenderer()
        elif report_format == "pdf":
            renderer = PdfReportRenderer()
        else:
            raise DomainError("unsupported_report_format", "Report format must be xlsx or pdf")
        handle = tempfile.NamedTemporaryFile(suffix=f".{renderer.extension}", delete=False)
        path = Path(handle.name)
        handle.close()
        try:
            await service.render_report(plan_id, renderer, path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return FileResponse(
            path,
            media_type=renderer.media_type,
            filename=f"beeline-day-{plan_id}.{renderer.extension}",
            background=BackgroundTask(_remove_file, str(path)),
        )

    return router
