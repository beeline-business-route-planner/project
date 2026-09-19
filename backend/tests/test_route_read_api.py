from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, event

from beeline_backend.domain.errors import DependencyUnavailableError
from beeline_backend.infrastructure.models import PlanRouteArtifactRow


class MemoryReadCache:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value

    async def aclose(self):
        pass


def prepared(client, synthetic_xlsx):
    imported = client.post(
        "/api/v1/imports", files={"file": ("Восток Синтетические данные.xlsx", synthetic_xlsx)}
    )
    assert imported.status_code == 200, imported.text
    scenario = imported.json()["scenario_id"]
    result = client.post(
        "/api/v1/plans/run", json={"scenario_id": scenario, "planning_date": "2026-08-17"}
    )
    assert result.status_code == 200, result.text
    plan = client.get(f"/api/v1/plans/{result.json()['plan_id']}").json()
    return scenario, plan


def test_saved_routes_cold_warm_corrupt_cache_and_no_provider_calls(client, synthetic_xlsx):
    _, plan = prepared(client, synthetic_xlsx)
    builder = client.app.state.route_builder

    async def forbidden(*args):
        raise AssertionError("GET must not call routing")

    builder.provider.route_geometry = forbidden
    builder.provider.matrix = forbidden
    cache = MemoryReadCache()
    client.app.state.route_reader.cache = cache
    queries = []
    event.listen(
        client.app.state.engine.sync_engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, *args: queries.append(statement),
    )
    engineer = plan["assignments"][0]["engineer_id"]
    overview = client.get(f"/api/v1/plans/{plan['id']}/routes")
    assert overview.status_code == 200, overview.text
    assert any(route["route_status"] == "empty" for route in overview.json()["routes"])
    url = f"/api/v1/plans/{plan['id']}/engineers/{engineer}/route"
    first = client.get(url)
    assert first.status_code == 200, first.text
    legacy = next(route for route in plan["routes"] if route["engineer_id"] == engineer)
    assert first.json()["geometry"]["coordinates"] == legacy["geometry"]["coordinates"]
    assert (
        len(first.json()["stops"])
        == sum(item["engineer_id"] == engineer for item in plan["assignments"]) + 1
    )
    queries.clear()
    assert client.get(url).json() == first.json()
    assert not any("plan_route_artifacts.detailed" in query for query in queries)
    cache.values = {key: "invalid JSON" for key in cache.values}
    assert client.get(url).json() == first.json()
    cache.values.clear()
    assert client.get(url).json() == first.json()
    assert client.get(f"/api/v1/plans/{plan['id']}").status_code == 200
    assert (
        client.get(
            f"/api/v1/engineers/{engineer}/route", params={"plan_id": plan["id"]}
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/plans/{uuid4()}/routes").status_code == 404
    assert client.get(f"/api/v1/plans/{plan['id']}/engineers/{uuid4()}/route").status_code == 404


def test_approval_changes_cached_response_revision(client, synthetic_xlsx):
    _, plan = prepared(client, synthetic_xlsx)
    client.app.state.route_reader.cache = MemoryReadCache()
    url = f"/api/v1/plans/{plan['id']}/routes"
    before = client.get(url).json()
    approved = client.post(
        f"/api/v1/plans/{plan['id']}/approve", json={"expected_base_plan_id": None, "actor": "test"}
    )
    assert approved.status_code == 200, approved.text
    after = client.get(url).json()
    assert after["status"] == "approved" and before["status"] == "draft"
    assert after["revision"] != before["revision"]


def test_manual_routing_failure_does_not_publish_a_partial_plan(client, synthetic_xlsx):
    scenario, plan = prepared(client, synthetic_xlsx)
    before = client.get(
        "/api/v1/plans", params={"scenario_id": scenario, "planning_date": "2026-08-17"}
    ).json()
    builder = client.app.state.route_builder

    async def empty_cache(keys):
        return {}

    async def unavailable(*args):
        raise DependencyUnavailableError("routing_unavailable", "test outage")

    builder.store.get_many = empty_cache
    builder.provider.route_geometry = unavailable
    assignment = plan["assignments"][0]
    response = client.post(
        f"/api/v1/plans/{plan['id']}/manual-change",
        json={
            "request_id": assignment["request_id"],
            "engineer_id": assignment["engineer_id"],
            "position": 1,
            "actor": "test",
            "reason": "atomicity check",
        },
    )
    assert response.status_code == 503, response.text
    after = client.get(
        "/api/v1/plans", params={"scenario_id": scenario, "planning_date": "2026-08-17"}
    ).json()
    assert len(after) == len(before)
    assert client.get(f"/api/v1/plans/{plan['id']}/routes").status_code == 200


def test_legacy_missing_artifacts_are_explicit_and_do_not_break_old_api(client, synthetic_xlsx):
    _, plan = prepared(client, synthetic_xlsx)

    async def remove_artifacts():
        async with client.app.state.session_factory() as session:
            await session.execute(delete(PlanRouteArtifactRow))
            await session.commit()

    client.portal.call(remove_artifacts)
    response = client.get(f"/api/v1/plans/{plan['id']}/routes")
    assert response.status_code == 409
    assert response.json()["code"] == "route_artifacts_unavailable"
    assert client.get(f"/api/v1/plans/{plan['id']}").json()["routes"] == plan["routes"]


def test_manual_change_rejects_a_stale_matrix_after_new_location(client, synthetic_xlsx):
    scenario, plan = prepared(client, synthetic_xlsx)
    created = client.post("/api/v1/requests", json={
        "scenario_id": scenario, "planning_date": "2026-08-17", "external_id": "new-location",
        "address": "Москва, новая контрольная точка", "district": "Центр",
        "window_start": "2026-08-17T08:00:00+03:00", "window_end": "2026-08-17T23:00:00+03:00",
        "service_minutes": 30, "required_skill": "local", "priority": "urgent",
        "idempotency_key": "new-location", "actor": "test"})
    assert created.status_code == 200, created.text
    assignment = plan["assignments"][0]
    changed = client.post(f'/api/v1/plans/{plan["id"]}/manual-change', json={
        "request_id": assignment["request_id"], "engineer_id": assignment["engineer_id"],
        "position": 1, "actor": "test", "reason": "stale matrix"})
    assert changed.status_code == 409, changed.text
    assert changed.json()["code"] == "manual_matrix_stale"
