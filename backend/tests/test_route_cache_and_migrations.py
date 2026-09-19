from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import create_engine, inspect, text

from beeline_backend.config import Settings
from beeline_backend.infrastructure.providers import NominatimGeocoder
from beeline_backend.infrastructure.route_store import RedisRouteCache
from beeline_backend.presentation.api import _provider_bundle


@pytest.mark.asyncio
async def test_redis_outage_fails_open_for_reads_and_writes():
    class FailingRedis:
        async def get(self, key):
            raise RedisConnectionError("offline")

        async def set(self, *args, **kwargs):
            raise RedisConnectionError("offline")

        async def aclose(self):
            pass

    cache = RedisRouteCache(None, 60, 0.05)
    cache.client = FailingRedis()
    assert await cache.get("key") is None
    await cache.set("key", "value")
    await cache.aclose()


def test_hybrid_geocoder_does_not_replace_real_addresses_with_demo_coordinates():
    _, geocoder, _, _ = _provider_bundle(
        Settings(_env_file=None, geocoder_mode="hybrid", routing_provider="demo")
    )
    assert isinstance(geocoder, NominatimGeocoder)


@pytest.mark.parametrize("populated", [False, True])
def test_migrations_fresh_and_populated_upgrade_roundtrip(tmp_path, populated):
    backend = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration.db"
    environment = dict(
        os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{database}", PYTHONPATH=str(backend / "src")
    )

    def migrate(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    if populated:
        migrate("upgrade", "0001_initial")
        engine = create_engine(f"sqlite:///{database}")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO scenarios(id, code, name, timezone, created_at) VALUES ('11111111111111111111111111111111', 'preserved', 'Preserved', 'Europe/Moscow', '2026-09-19 00:00:00')"
                )
            )
        engine.dispose()
    migrate("upgrade", "head")
    migrate("downgrade", "0001_initial")
    migrate("upgrade", "head")
    engine = create_engine(f"sqlite:///{database}")
    assert "plan_route_artifacts" in inspect(engine).get_table_names()
    assert "route_cache_id" in {
        column["name"] for column in inspect(engine).get_columns("route_legs")
    }
    with engine.connect() as connection:
        if populated:
            assert (
                connection.scalar(text("SELECT count(*) FROM scenarios WHERE code='preserved'"))
                == 1
            )
    engine.dispose()
