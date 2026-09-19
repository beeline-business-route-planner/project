from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from beeline_backend.application.routing import (
    DetailedResponse,
    OverviewResponse,
    RouteDetailed,
    RouteOverview,
    SegmentData,
    digest,
)
from beeline_backend.domain.errors import ConflictError, NotFoundError
from beeline_backend.infrastructure.models import PlanRouteArtifactRow, PlanRow, RouteCacheRow

logger = logging.getLogger(__name__)


class SqlSegmentStore:
    """Each call owns a session; HTTP workers never share an AsyncSession."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def get_many(self, keys: list[str]) -> dict[str, SegmentData]:
        found: dict[str, SegmentData] = {}
        async with self.factory() as session:
            for start in range(0, len(keys), 400):
                rows = await session.scalars(
                    select(RouteCacheRow).where(
                        RouteCacheRow.cache_key.in_(keys[start : start + 400])
                    )
                )
                for row in rows:
                    try:
                        value = SegmentData.model_validate(row.geometry)
                    except ValidationError:
                        continue  # older, unrelated cache formats are never treated as road segments
                    if value.key == row.cache_key and value.cache_id == row.id:
                        found[row.cache_key] = value
        return found

    async def put(self, segment: SegmentData) -> None:
        async with self.factory() as session, session.begin():
            insert = (
                sqlite_insert
                if session.bind is not None and session.bind.dialect.name == "sqlite"
                else pg_insert
            )
            statement = (
                insert(RouteCacheRow)
                .values(
                    id=segment.cache_id,
                    cache_key=segment.key,
                    provider=segment.provider,
                    provider_version=segment.graph_fingerprint,
                    profile=segment.profile,
                    origin={"longitude": segment.origin[0], "latitude": segment.origin[1]},
                    destination={
                        "longitude": segment.destination[0],
                        "latitude": segment.destination[1],
                    },
                    duration_seconds=round(segment.duration_seconds),
                    distance_meters=round(segment.distance_meters),
                    geometry=segment.model_dump(mode="json"),
                    captured_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["cache_key"])
            )
            await session.execute(statement)


class ReadCache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str) -> None: ...
    async def aclose(self) -> None: ...


class RedisRouteCache:
    def __init__(self, url: str | None, ttl: int, timeout: float) -> None:
        self.client: Redis | None = (
            Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=timeout,
                socket_timeout=timeout,
                retry_on_timeout=False,
                max_connections=32,
            )
            if url
            else None
        )
        self.ttl = ttl

    async def get(self, key: str) -> str | None:
        if self.client is None:
            return None
        try:
            value = await self.client.get(key)
            logger.info("route_cache %s", "hit" if value is not None else "miss")
            return cast(str | None, value)
        except (RedisError, OSError, TimeoutError):
            logger.warning("route_cache read_error")
            return None

    async def set(self, key: str, value: str) -> None:
        if self.client is None:
            return
        try:
            await self.client.set(key, value, ex=self.ttl)
        except (RedisError, OSError, TimeoutError):
            logger.warning("route_cache write_error")

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()


class RouteReader:
    def __init__(self, factory: async_sessionmaker[AsyncSession], cache: ReadCache) -> None:
        self.factory = factory
        self.cache = cache

    async def _context(self, plan_id: UUID, engineer_id: UUID | None = None) -> tuple[str, str]:
        async with self.factory() as session:
            plan = (
                await session.execute(
                    select(PlanRow.status, PlanRow.version).where(PlanRow.id == plan_id)
                )
            ).one_or_none()
            if plan is None:
                raise NotFoundError("plan_not_found", "Plan not found")
            statement = select(
                PlanRouteArtifactRow.engineer_id, PlanRouteArtifactRow.revision
            ).where(PlanRouteArtifactRow.plan_id == plan_id)
            if engineer_id is not None:
                statement = statement.where(PlanRouteArtifactRow.engineer_id == engineer_id)
            rows = (
                await session.execute(statement.order_by(PlanRouteArtifactRow.engineer_id))
            ).all()
            if not rows:
                if engineer_id is not None:
                    snapshot = await session.scalar(
                        select(PlanRow.input_snapshot).where(PlanRow.id == plan_id)
                    )
                    engineers = snapshot.get("engineers", []) if snapshot else []
                    if not isinstance(engineers, list):
                        engineers = []
                    if not any(
                        isinstance(item, dict) and item.get("id") == str(engineer_id)
                        for item in engineers
                    ):
                        raise NotFoundError(
                            "engineer_not_in_plan", "Engineer is not in the plan snapshot"
                        )
                raise ConflictError(
                    "route_artifacts_unavailable",
                    "Saved plan has no versioned route artifacts; explicitly rebuild as a new plan",
                    {"plan_id": str(plan_id), "reason": "legacy_plan"},
                )
            revision = digest(
                [plan.version, [(str(row.engineer_id), row.revision) for row in rows]]
            )
            return str(plan.status), revision

    async def overview(self, plan_id: UUID) -> OverviewResponse:
        status, revision = await self._context(plan_id)
        key = f"routes:v1:plan:{plan_id}:revision:{revision}:overview"
        cached = await self.cache.get(key)
        if cached is not None:
            try:
                result = OverviewResponse.model_validate_json(cached)
                if (
                    result.plan_id == plan_id
                    and result.revision == revision
                    and result.status == status
                ):
                    return result
            except (ValueError, ValidationError):
                logger.warning("route_cache corrupt_overview")
        async with self.factory() as session:
            rows = await session.scalars(
                select(PlanRouteArtifactRow.overview)
                .where(PlanRouteArtifactRow.plan_id == plan_id)
                .order_by(PlanRouteArtifactRow.engineer_id)
            )
            result = OverviewResponse(
                plan_id=plan_id,
                revision=revision,
                status=status,
                routes=[RouteOverview.model_validate(row) for row in rows],
            )
        await self.cache.set(key, result.model_dump_json())
        return result

    async def detailed(self, plan_id: UUID, engineer_id: UUID) -> DetailedResponse:
        status, revision = await self._context(plan_id, engineer_id)
        key = f"routes:v1:plan:{plan_id}:revision:{revision}:engineer:{engineer_id}:detailed"
        cached = await self.cache.get(key)
        if cached is not None:
            try:
                result = DetailedResponse.model_validate_json(cached)
                if (
                    result.plan_id == plan_id
                    and result.engineer_id == engineer_id
                    and result.revision == revision
                    and result.status == status
                ):
                    return result
            except (ValueError, ValidationError):
                logger.warning("route_cache corrupt_detailed")
        async with self.factory() as session:
            payload = await session.scalar(
                select(PlanRouteArtifactRow.detailed).where(
                    PlanRouteArtifactRow.plan_id == plan_id,
                    PlanRouteArtifactRow.engineer_id == engineer_id,
                )
            )
            detailed = RouteDetailed.model_validate(payload)
            result = DetailedResponse(
                **detailed.model_dump(), plan_id=plan_id, revision=revision, status=status
            )
        await self.cache.set(key, result.model_dump_json())
        return result

    async def warm(self, plan_id: UUID) -> None:
        # Called only after SQL commit. Cache warming must not turn success into a failed run.
        try:
            await self.overview(plan_id)
        except Exception:
            logger.warning("route_cache warm_failed plan_id=%s", plan_id)
