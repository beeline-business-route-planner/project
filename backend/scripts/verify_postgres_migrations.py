#!/usr/bin/env python3
"""Verify upgrades in a newly created, uniquely named PostgreSQL database, then remove it."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import make_url


async def main(server_url: str) -> None:
    url = make_url(server_url)
    admin = await asyncpg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    database_name = "routing_migration_" + uuid4().hex[:12]
    backend = Path(__file__).resolve().parents[1]
    database_url = url.set(
        drivername="postgresql+asyncpg", database=database_name
    ).render_as_string(hide_password=False)
    environment = dict(os.environ, DATABASE_URL=database_url, PYTHONPATH=str(backend / "src"))
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    checks = []

    async def migrate(*args):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            *args,
            cwd=backend,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode:
            raise RuntimeError((stdout + stderr).decode())

    async def connect():
        return await asyncpg.connect(
            url.set(drivername="postgresql", database=database_name).render_as_string(
                hide_password=False
            )
        )

    try:
        await migrate("upgrade", "0001_initial")
        connection = await connect()
        try:
            await connection.execute(
                "INSERT INTO scenarios(id, code, name, timezone, created_at) VALUES ($1, 'preserved', 'Preserved', 'Europe/Moscow', now())",
                uuid4(),
            )
        finally:
            await connection.close()
        await migrate("upgrade", "head")
        await migrate("check")
        checks.append("populated 0001 -> head; ORM metadata matches")
        await migrate("downgrade", "0001_initial")
        await migrate("upgrade", "head")
        connection = await connect()
        try:
            assert (
                await connection.fetchval("SELECT count(*) FROM scenarios WHERE code='preserved'")
                == 1
            )
            assert (
                await connection.fetchval("SELECT to_regclass('plan_route_artifacts')") is not None
            )
        finally:
            await connection.close()
        checks.append("downgrade/upgrade preserves existing data")
        await migrate("downgrade", "base")
        await migrate("upgrade", "head")
        await migrate("check")
        checks.append("empty database -> head; ORM metadata matches")
        print(json.dumps({"postgres_migrations": "passed", "checks": checks}, indent=2))
    finally:
        await admin.execute(f'DROP DATABASE "{database_name}" WITH (FORCE)')
        await admin.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server-url",
        required=True,
        help="Development PostgreSQL connection allowed to create a temporary database",
    )
    arguments = parser.parse_args()
    asyncio.run(main(arguments.server_url))
