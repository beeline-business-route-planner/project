"""Layer selection, scenario catalog checks, and disposable E2E resources."""

import asyncio
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from tests.support.scenarios import load_scenarios

# Applied before pytest imports test modules or src.config. No developer DB or
# external-service credentials from config.toml are usable in a test run.
os.environ.update(
    {
        "DATABASE__POSTGRES_USERNAME": "test_only",
        "DATABASE__POSTGRES_PASSWORD": "test_only",
        "DATABASE__POSTGRES_DB": "planner_test_forbidden",
        "DATABASE__POSTGRES_HOST": "127.0.0.1",
        "DATABASE__POSTGRES_PORT": "1",
        "DATABASE__ALEMBIC_POSTGRES_HOST": "127.0.0.1",
        "GEOCODING__API_KEY": "",
        "DGIS__API_KEY": "",
        "S3__ACCESS_KEY": "test_only",
        "S3__SECRET_KEY": "test_only",
        "S3__ENDPOINT_URL": "http://127.0.0.1:1",
        "S3__PUBLIC_ENDPOINT_URL": "http://127.0.0.1:1",
    }
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--suite",
        choices=("unit", "integration", "e2e", "full"),
        default="unit",
        help="Select the architectural test layer (default: unit).",
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    root = Path(__file__).parent
    try:
        relative = collection_path.relative_to(root)
    except ValueError:
        return False
    layer = relative.parts[0] if relative.parts else ""
    suite = config.getoption("--suite")
    return layer in {"unit", "integration", "e2e"} and suite != "full" and layer != suite


def pytest_sessionstart(session: pytest.Session) -> None:
    if session.config.getoption("--suite") == "unit":
        return
    from testcontainers.community.postgres import PostgresContainer

    container = None
    try:
        container = PostgresContainer(
            "postgres:16-alpine",
            username="test_only",
            password="test_only",
            dbname="planner_test_bootstrap",
        )
        container.start()
        session.config._planner_test_postgres = container
        url = make_url(container.get_connection_url()).set(drivername="postgresql+asyncpg")
        suite = session.config.getoption("--suite")
        cases = (
            ("integration",)
            if suite == "integration"
            else ("g02", "g03", "g05", "t05", "t07", "t08", "manual")
        )
        if suite == "full":
            cases = ("integration", "g02", "g03", "g05", "t05", "t07", "t08", "manual")

        async def create_databases() -> None:
            connection = await asyncpg.connect(
                host=url.host,
                port=url.port,
                user=url.username,
                password=url.password,
                database=url.database,
            )
            try:
                for case in cases:
                    await connection.execute(f'CREATE DATABASE "{case}_test_suite"')
            finally:
                await connection.close()

        asyncio.run(create_databases())
        root = Path(__file__).resolve().parents[1]
        for case in cases:
            database = f"{case}_test_suite"
            test_url = url.set(database=database)
            variable = (
                "INTEGRATION_TEST_DATABASE_URL"
                if case == "integration"
                else f"{case.upper()}_TEST_DATABASE_URL"
            )
            os.environ[variable] = test_url.render_as_string(hide_password=False)
            env = os.environ.copy()
            env.update(
                {
                    "DATABASE__POSTGRES_HOST": url.host or "127.0.0.1",
                    "DATABASE__POSTGRES_PORT": str(url.port),
                    "DATABASE__POSTGRES_DB": database,
                }
            )
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
            )
    except Exception as exc:
        if container is not None:
            container.stop()
        pytest.exit(f"E2E requires Docker and migrated disposable PostgreSQL: {exc}", returncode=2)


def pytest_sessionfinish(session: pytest.Session) -> None:
    container = getattr(session.config, "_planner_test_postgres", None)
    if container is not None:
        container.stop()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    root = Path(__file__).parent
    scenarios = load_scenarios(root / "scenarios.toml")
    collected: set[str] = set()
    for item in items:
        scenario = scenarios.get(item.nodeid)
        if scenario is None:
            raise pytest.UsageError(f"Test is absent from tests/scenarios.toml: {item.nodeid}")
        collected.add(item.nodeid)
        item.add_marker(pytest.mark.case(scenario.id))
    full_tree = any(Path(argument).resolve() == root for argument in config.args)
    if full_tree:
        suite = config.getoption("--suite")
        layers = {"unit", "integration", "e2e"} if suite == "full" else {suite}
        required = {node for node, scenario in scenarios.items() if scenario.layer in layers}
        missing = required - collected
        if missing:
            description = ", ".join(sorted(missing))
            raise pytest.UsageError(f"Manifest scenarios were not collected: {description}")


@pytest.fixture(autouse=True)
def block_unapproved_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    layer = Path(str(request.node.path)).relative_to(Path(__file__).parent).parts[0]
    real_connect = socket.socket.connect

    def guarded_connect(sock: socket.socket, address: object) -> object:
        host = address[0] if isinstance(address, tuple) else None
        if layer in {"integration", "e2e"} and host in {"127.0.0.1", "::1", "localhost"}:
            return real_connect(sock, address)
        raise RuntimeError(f"Network is forbidden in {layer} tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield
