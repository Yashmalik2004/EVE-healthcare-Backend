"""Tests for GET /health endpoint."""

from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    """Health endpoint returns 200 with healthy status and required fields."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert "app_name" in data
    assert data["database"] == "healthy"
    assert "timestamp" in data
    assert "environment" in data


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
