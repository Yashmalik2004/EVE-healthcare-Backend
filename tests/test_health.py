"""Tests for GET /health endpoint and service observability."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    """Health endpoint returns 200 with healthy status, required fields, and no credential leaks."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert "app_name" in data
    assert data["database"] == "healthy"
    assert "timestamp" in data
    assert "environment" in data
    assert "version" in data
    assert "api_version" in data

    # Verify no database connection strings or credentials leak in the response
    for key, value in data.items():
        assert "password" not in str(key).lower()
        assert "password" not in str(value).lower()
        assert "secret" not in str(key).lower()
        assert "secret" not in str(value).lower()
        assert "postgres://" not in str(value).lower()
        assert "postgresql://" not in str(value).lower()


def test_health_check_degraded_when_db_down(client: TestClient):
    """Health endpoint gracefully degrades when database query fails without 500 crash."""
    from app.db.database import get_db

    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("DB connection timeout")

    client.app.dependency_overrides[get_db] = lambda: mock_db
    try:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unhealthy"
    finally:
        client.app.dependency_overrides.pop(get_db, None)


def test_root_overview(client: TestClient):
    """Root endpoint returns service overview with correct keys."""
    response = client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert "service" in data
    assert "environment" in data
    assert data["docs_url"] == "/docs"
    assert data["health_check"] == "/health"
    assert "api_v1_prefix" in data


def test_openapi_spec_has_bearer_auth(client: TestClient):
    """OpenAPI schema generation includes BearerAuth security scheme and tag metadata."""
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    assert "openapi" in schema
    assert "components" in schema
    assert "securitySchemes" in schema["components"]
    assert "BearerAuth" in schema["components"]["securitySchemes"]

    bearer_auth = schema["components"]["securitySchemes"]["BearerAuth"]
    assert bearer_auth["type"] == "http"
    assert bearer_auth["scheme"] == "bearer"
    assert bearer_auth["bearerFormat"] == "JWT"

    tags = [t["name"] for t in schema.get("tags", [])]
    assert "Authentication" in tags
    assert "Bookings" in tags
    assert "Diagnostic Centres" in tags
    assert "Diagnostic Tests" in tags
    assert "Payments" in tags
    assert "Health" in tags


def test_consistent_error_response_404(client: TestClient):
    """Non-existent route returns consistent error envelope with code and message."""
    response = client.get("/api/v1/nonexistent-route-xyz")
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "error" in data
    assert "code" in data["error"]
    assert "message" in data["error"]
    assert data["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_consistent_error_response_405(client: TestClient):
    """Method not allowed returns consistent error envelope."""
    response = client.delete("/health")
    assert response.status_code == 405
    data = response.json()
    assert data["success"] is False
    assert "error" in data
    assert data["error"]["code"] == "METHOD_NOT_ALLOWED"
