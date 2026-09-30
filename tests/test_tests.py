"""Diagnostic Tests catalogue test suite — Phase 4.

Covers:
- POST /api/v1/tests (create test, auth required, validation, empty name rejection)
- GET /api/v1/tests (list tests, category filter, pagination, public access)
- GET /api/v1/tests/{test_id} (retrieve test, invalid ID, nonexistent ID, public access)
"""

import pytest
from fastapi.testclient import TestClient


def get_auth_headers(client: TestClient, email: str = "testmgr@example.com") -> dict[str, str]:
    """Helper to register and login a user to get Bearer auth headers."""
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "SecurePassword123!", "full_name": "Test Manager"},
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "SecurePassword123!"},
    )
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_and_get_test(client: TestClient):
    """Creating a diagnostic test succeeds and can be retrieved publicly by ID."""
    headers = get_auth_headers(client, "catalogue_admin@example.com")
    payload = {
        "name": "Lipid Profile Panel",
        "description": "Cholesterol, Triglycerides, HDL, LDL",
        "category": "Biochemistry",
        "is_active": True,
    }
    create_res = client.post("/api/v1/tests", json=payload, headers=headers)
    assert create_res.status_code == 201
    test_data = create_res.json()
    assert test_data["name"] == "Lipid Profile Panel"
    assert test_data["category"] == "Biochemistry"
    assert test_data["is_active"] is True
    assert "id" in test_data
    test_id = test_data["id"]

    # Public retrieval
    get_res = client.get(f"/api/v1/tests/{test_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == test_id
    assert get_res.json()["name"] == "Lipid Profile Panel"


def test_create_test_unauthorized(client: TestClient):
    """Creating a test without auth header fails with 401."""
    payload = {
        "name": "Unauthorized Test",
        "category": "General",
    }
    response = client.post("/api/v1/tests", json=payload)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_create_test_empty_name(client: TestClient):
    """Creating a test with empty or whitespace name returns 422."""
    headers = get_auth_headers(client, "empty_tester@example.com")
    payload = {
        "name": "   ",
        "category": "Biochemistry",
    }
    response = client.post("/api/v1/tests", json=payload, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_nonexistent_test(client: TestClient):
    """Retrieving a non-existent test ID returns 404."""
    response = client.get("/api/v1/tests/99999")
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "DIAGNOSTICTEST_NOT_FOUND"


def test_get_invalid_test_id_format(client: TestClient):
    """Retrieving a test with ID <= 0 returns 422."""
    response = client.get("/api/v1/tests/0")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_tests_filter_and_pagination(client: TestClient):
    """Listing tests supports category filtering, active status, and pagination."""
    headers = get_auth_headers(client, "test_lister@example.com")
    client.post(
        "/api/v1/tests",
        json={"name": "TSH Test", "category": "Endocrinology"},
        headers=headers,
    )
    client.post(
        "/api/v1/tests",
        json={"name": "Vitamin D3", "category": "Endocrinology"},
        headers=headers,
    )
    client.post(
        "/api/v1/tests",
        json={"name": "Blood Glucose Fasting", "category": "Diabetes"},
        headers=headers,
    )

    # Filter category
    res = client.get("/api/v1/tests?category=Endocrinology")
    assert res.status_code == 200
    tests = res.json()
    assert len(tests) >= 2
    assert all(t["category"] == "Endocrinology" for t in tests)

    # Pagination skip & limit
    paged_res = client.get("/api/v1/tests?skip=0&limit=2")
    assert paged_res.status_code == 200
    assert len(paged_res.json()) <= 2
