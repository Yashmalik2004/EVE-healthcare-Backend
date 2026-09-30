"""Diagnostic Centres and Centre-Test Association test suite — Phase 4.

Covers:
- POST /api/v1/centres (create centre, auth required, validation)
- GET /api/v1/centres (list centres, filter city, pagination, public)
- GET /api/v1/centres/{centre_id} (retrieve centre, invalid ID, nonexistent ID, public)
- PATCH /api/v1/centres/{centre_id} (update centre, auth required)
- POST /api/v1/centres/{centre_id}/tests (associate test, duplicate association, invalid price, nonexistent test)
- GET /api/v1/centres/{centre_id}/tests (list centre tests, centre-specific pricing)
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


def get_auth_headers(client: TestClient, email: str = "staff@example.com") -> dict[str, str]:
    """Helper to register and login a user to get Bearer auth headers."""
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "SecurePassword123!", "full_name": "Staff User"},
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "SecurePassword123!"},
    )
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Centre CRUD Tests ─────────────────────────────────────────────────────────


def test_create_and_get_centre(client: TestClient):
    """Creating a diagnostic centre succeeds and can be retrieved publicly by ID."""
    headers = get_auth_headers(client, "centre_admin@example.com")
    payload = {
        "name": "EVE Central Diagnostic Lab",
        "address": "123 Healthcare Ave",
        "city": "Bengaluru",
        "state": "Karnataka",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "is_active": True,
    }
    create_res = client.post("/api/v1/centres", json=payload, headers=headers)
    assert create_res.status_code == 201
    centre_data = create_res.json()
    assert centre_data["name"] == "EVE Central Diagnostic Lab"
    assert centre_data["city"] == "Bengaluru"
    assert centre_data["state"] == "Karnataka"
    assert centre_data["is_active"] is True
    assert "id" in centre_data
    centre_id = centre_data["id"]

    # Public retrieval without auth header
    get_res = client.get(f"/api/v1/centres/{centre_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == centre_id
    assert get_res.json()["name"] == "EVE Central Diagnostic Lab"


def test_create_centre_unauthorized(client: TestClient):
    """Creating a centre without authentication header fails with 401."""
    payload = {
        "name": "Unauthorized Centre",
        "address": "100 Main St",
        "city": "Pune",
        "state": "Maharashtra",
    }
    response = client.post("/api/v1/centres", json=payload)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_create_centre_empty_name(client: TestClient):
    """Creating a centre with an empty or whitespace name returns 422."""
    headers = get_auth_headers(client, "validator@example.com")
    payload = {
        "name": "   ",
        "address": "123 Valid St",
        "city": "Mumbai",
        "state": "Maharashtra",
    }
    response = client.post("/api/v1/centres", json=payload, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_nonexistent_centre(client: TestClient):
    """Retrieving a non-existent centre ID returns 404."""
    response = client.get("/api/v1/centres/99999")
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "DIAGNOSTICCENTRE_NOT_FOUND"


def test_get_invalid_centre_id_format(client: TestClient):
    """Retrieving a centre with invalid ID (<= 0) returns 422."""
    response = client.get("/api/v1/centres/0")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_centres_filter_and_pagination(client: TestClient):
    """Listing centres supports city filtering, active status, and pagination."""
    headers = get_auth_headers(client, "lister@example.com")
    client.post(
        "/api/v1/centres",
        json={"name": "Mumbai Centre", "address": "10 Marine Drive", "city": "Mumbai", "state": "MH"},
        headers=headers,
    )
    client.post(
        "/api/v1/centres",
        json={"name": "Delhi Centre", "address": "20 Ring Road", "city": "Delhi", "state": "DL"},
        headers=headers,
    )

    # Filter city
    res = client.get("/api/v1/centres?city=Mumbai")
    assert res.status_code == 200
    centres = res.json()
    assert len(centres) >= 1
    assert all("mumbai" in c["city"].lower() for c in centres)

    # Pagination skip & limit
    paged_res = client.get("/api/v1/centres?skip=0&limit=1")
    assert paged_res.status_code == 200
    assert len(paged_res.json()) <= 1


def test_update_centre(client: TestClient):
    """PATCH /centres/{id} updates specified fields."""
    headers = get_auth_headers(client, "updater@example.com")
    create_res = client.post(
        "/api/v1/centres",
        json={"name": "Old Centre Name", "address": "100 MG Road", "city": "Pune", "state": "MH"},
        headers=headers,
    )
    centre_id = create_res.json()["id"]

    patch_res = client.patch(
        f"/api/v1/centres/{centre_id}",
        json={"name": "Updated Centre Name", "city": "Nagpur"},
        headers=headers,
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["name"] == "Updated Centre Name"
    assert updated["city"] == "Nagpur"
    assert updated["address"] == "100 MG Road"


def test_update_nonexistent_centre(client: TestClient):
    """Updating a non-existent centre returns 404."""
    headers = get_auth_headers(client, "updater_404@example.com")
    res = client.patch(
        "/api/v1/centres/99999",
        json={"name": "Ghost Centre"},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "DIAGNOSTICCENTRE_NOT_FOUND"


# ── Centre-Test Association & Pricing Tests ───────────────────────────────────


def test_centre_test_association_and_duplicate(client: TestClient):
    """Associating a test with a centre succeeds; duplicate association returns 409."""
    headers = get_auth_headers(client, "assoc_admin@example.com")

    # Create centre
    centre_res = client.post(
        "/api/v1/centres",
        json={"name": "Apollo Clinic", "address": "12 Residency Rd", "city": "Bengaluru", "state": "KA"},
        headers=headers,
    )
    centre_id = centre_res.json()["id"]

    # Create test
    test_res = client.post(
        "/api/v1/tests",
        json={
            "name": "Complete Blood Count (CBC)",
            "description": "Measures WBC, RBC, platelets",
            "category": "Hematology",
        },
        headers=headers,
    )
    test_id = test_res.json()["id"]

    # Associate test with centre
    add_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": test_id, "price": 499.50},
        headers=headers,
    )
    assert add_res.status_code == 201
    assoc_data = add_res.json()
    assert assoc_data["centre_id"] == centre_id
    assert assoc_data["test_id"] == test_id
    assert Decimal(str(assoc_data["price"])) == Decimal("499.50")
    assert assoc_data["is_available"] is True
    assert assoc_data["test"]["name"] == "Complete Blood Count (CBC)"

    # Duplicate association attempt returns 409
    dup_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": test_id, "price": 550.00},
        headers=headers,
    )
    assert dup_res.status_code == 409
    assert dup_res.json()["error"]["code"] == "DUPLICATE_CENTRE_TEST"


def test_associate_test_invalid_prices(client: TestClient):
    """Prices <= 0 or non-numeric must be rejected with 422."""
    headers = get_auth_headers(client, "price_tester@example.com")

    centre_res = client.post(
        "/api/v1/centres",
        json={"name": "Pricing Centre", "address": "1 Road", "city": "Goa", "state": "GA"},
        headers=headers,
    )
    centre_id = centre_res.json()["id"]

    test_res = client.post(
        "/api/v1/tests",
        json={"name": "Urine Routine", "category": "Biochemistry"},
        headers=headers,
    )
    test_id = test_res.json()["id"]

    # Negative price
    neg_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": test_id, "price": -50.00},
        headers=headers,
    )
    assert neg_res.status_code == 422
    assert neg_res.json()["error"]["code"] == "VALIDATION_ERROR"

    # Zero price
    zero_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": test_id, "price": 0.00},
        headers=headers,
    )
    assert zero_res.status_code == 422
    assert zero_res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_associate_test_nonexistent_centre_or_test(client: TestClient):
    """Associating with nonexistent centre or test ID returns 404."""
    headers = get_auth_headers(client, "notfound_assoc@example.com")

    centre_res = client.post(
        "/api/v1/centres",
        json={"name": "Valid Centre", "address": "1 St", "city": "Jaipur", "state": "RJ"},
        headers=headers,
    )
    valid_centre_id = centre_res.json()["id"]

    test_res = client.post(
        "/api/v1/tests",
        json={"name": "Valid Test", "category": "Pathology"},
        headers=headers,
    )
    valid_test_id = test_res.json()["id"]

    # Nonexistent centre
    res1 = client.post(
        "/api/v1/centres/99999/tests",
        json={"test_id": valid_test_id, "price": 100.00},
        headers=headers,
    )
    assert res1.status_code == 404
    assert res1.json()["error"]["code"] == "DIAGNOSTICCENTRE_NOT_FOUND"

    # Nonexistent test
    res2 = client.post(
        f"/api/v1/centres/{valid_centre_id}/tests",
        json={"test_id": 99999, "price": 100.00},
        headers=headers,
    )
    assert res2.status_code == 404
    assert res2.json()["error"]["code"] == "DIAGNOSTICTEST_NOT_FOUND"


def test_centre_specific_pricing(client: TestClient):
    """Verify that the same test can have different prices at different centres.

    CBC:
    Centre A -> 500.00
    Centre B -> 650.00
    """
    headers = get_auth_headers(client, "pricing_diff@example.com")

    # Create Centre A and Centre B
    res_a = client.post(
        "/api/v1/centres",
        json={"name": "Centre A", "address": "100 North Rd", "city": "Kolkata", "state": "WB"},
        headers=headers,
    )
    centre_a_id = res_a.json()["id"]

    res_b = client.post(
        "/api/v1/centres",
        json={"name": "Centre B", "address": "200 South Rd", "city": "Kolkata", "state": "WB"},
        headers=headers,
    )
    centre_b_id = res_b.json()["id"]

    # Create CBC test
    res_test = client.post(
        "/api/v1/tests",
        json={"name": "CBC", "category": "Hematology"},
        headers=headers,
    )
    test_id = res_test.json()["id"]

    # Associate at Centre A for 500.00
    client.post(
        f"/api/v1/centres/{centre_a_id}/tests",
        json={"test_id": test_id, "price": 500.00},
        headers=headers,
    )

    # Associate at Centre B for 650.00
    client.post(
        f"/api/v1/centres/{centre_b_id}/tests",
        json={"test_id": test_id, "price": 650.00},
        headers=headers,
    )

    # Query tests at Centre A
    list_a = client.get(f"/api/v1/centres/{centre_a_id}/tests").json()
    assert len(list_a) == 1
    assert Decimal(str(list_a[0]["price"])) == Decimal("500.00")

    # Query tests at Centre B
    list_b = client.get(f"/api/v1/centres/{centre_b_id}/tests").json()
    assert len(list_b) == 1
    assert Decimal(str(list_b[0]["price"])) == Decimal("650.00")


def test_list_centre_tests_nonexistent_centre(client: TestClient):
    """Listing tests for a nonexistent centre returns 404."""
    res = client.get("/api/v1/centres/99999/tests")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "DIAGNOSTICCENTRE_NOT_FOUND"


def test_associate_test_inactive_centre_or_test(client: TestClient):
    """Associating with inactive centre or inactive test returns 422 with validation code."""
    headers = get_auth_headers(client, "inactive_assoc@example.com")

    # Inactive centre
    centre_res = client.post(
        "/api/v1/centres",
        json={"name": "Inactive Centre", "address": "1 Rd", "city": "Surat", "state": "GJ", "is_active": False},
        headers=headers,
    )
    inactive_centre_id = centre_res.json()["id"]

    # Active test
    test_res = client.post(
        "/api/v1/tests",
        json={"name": "Active Test", "category": "General"},
        headers=headers,
    )
    active_test_id = test_res.json()["id"]

    res1 = client.post(
        f"/api/v1/centres/{inactive_centre_id}/tests",
        json={"test_id": active_test_id, "price": 100.00},
        headers=headers,
    )
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "INACTIVE_CENTRE"

    # Active centre with Inactive test
    centre_res2 = client.post(
        "/api/v1/centres",
        json={"name": "Active Centre 2", "address": "2 Rd", "city": "Surat", "state": "GJ"},
        headers=headers,
    )
    active_centre_id = centre_res2.json()["id"]

    test_res2 = client.post(
        "/api/v1/tests",
        json={"name": "Inactive Test", "category": "General", "is_active": False},
        headers=headers,
    )
    inactive_test_id = test_res2.json()["id"]

    res2 = client.post(
        f"/api/v1/centres/{active_centre_id}/tests",
        json={"test_id": inactive_test_id, "price": 100.00},
        headers=headers,
    )
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] == "INACTIVE_TEST"

