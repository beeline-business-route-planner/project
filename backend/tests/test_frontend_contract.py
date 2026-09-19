from __future__ import annotations

from fastapi.testclient import TestClient


def test_cors_preflight_allows_configured_frontend(client: TestClient) -> None:
    response = client.options(
        "/api/v1/requests",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,idempotency-key,x-correlation-id",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://testserver"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()


def test_cors_exposes_correlation_id_to_frontend(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health",
        headers={"Origin": "http://testserver", "X-Correlation-ID": "frontend-test"},
    )

    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == "frontend-test"
    assert response.headers["access-control-allow-origin"] == "http://testserver"
    assert "X-Correlation-ID" in response.headers["access-control-expose-headers"]


def test_request_validation_uses_shared_error_contract(client: TestClient) -> None:
    response = client.post("/api/v1/plans/run", json={})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["correlation_id"]


def test_openapi_contains_typed_frontend_responses(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    dashboard_schema = schema["paths"]["/api/v1/dashboard"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    request_list_schema = schema["paths"]["/api/v1/requests"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]

    assert dashboard_schema["$ref"].endswith("/DashboardResponse")
    assert request_list_schema["items"]["$ref"].endswith("/RequestListItemResponse")
    assert "ErrorBody" in schema["components"]["schemas"]
