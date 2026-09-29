"""A disposable PostgreSQL database reaches the repository's Alembic head."""

import os
import unittest

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url


class MigrationIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_database_is_migrated_to_single_head(self) -> None:
        url = make_url(os.environ["INTEGRATION_TEST_DATABASE_URL"])
        self.assertEqual(url.drivername, "postgresql+asyncpg")
        self.assertEqual(url.database, "integration_test_suite")
        self.assertIn(url.host, {"127.0.0.1", "localhost"})

        script = ScriptDirectory.from_config(Config("alembic.ini"))
        heads = script.get_heads()
        self.assertEqual(len(heads), 1)

        connection = await asyncpg.connect(
            host=url.host,
            port=url.port,
            user=url.username,
            password=url.password,
            database=url.database,
        )
        try:
            revision = await connection.fetchval("SELECT version_num FROM alembic_version")
            self.assertEqual(revision, heads[0])
        finally:
            await connection.close()
