"""AppointmentSlot test suite — Phase 5.

Covers:
- POST /api/v1/centres/{centre_id}/slots (create valid slot, auth required, future datetime check, duplicate rejection)
- GET /api/v1/centres/{centre_id}/slots (retrieve slots, availability filter, pagination, public access)
- Error handling: nonexistent centre (404), invalid centre ID (422), past datetime (422), duplicate slot (409)
- Concurrency locking preparation: row-level locking reservation (reserve_slot_concurrency_safe)
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, NotFoundException
from app.models.appointment_slot import AppointmentSlot
from app.services.slot_service import slot_service


def get_auth_headers(client: TestClient, email: str = "slotmgr@example.com") -> dict[str, str]:
    """Register and login a staff user to obtain Bearer auth headers."""
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "SecurePassword123!", "full_name": "Slot Manager"},
    )
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "SecurePassword123!"},
    )
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_test_centre(client: TestClient, headers: dict[str, str], name: str = "Test Centre") -> int:
    """Helper to create a test centre and return its ID."""
    res = client.post(
        "/api/v1/centres",
        json={"name": name, "address": "100 Health Way", "city": "Bengaluru", "state": "Karnataka"},
        headers=headers,
    )
    return res.json()["id"]


# ── Slot Creation Tests ───────────────────────────────────────────────────────


def test_create_valid_slot(client: TestClient):
    """Creating a future appointment slot succeeds and returns 201 Created."""
    headers = get_auth_headers(client, "valid_slot@example.com")
    centre_id = create_test_centre(client, headers, "Future Lab")

    future_dt = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    payload = {
        "appointment_datetime": future_dt,
        "is_available": True,
    }
    response = client.post(f"/api/v1/centres/{centre_id}/slots", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["centre_id"] == centre_id
    assert data["is_available"] is True
    assert "id" in data
    assert "created_at" in data


def test_create_slot_unauthorized(client: TestClient):
    """Creating a slot without Authorization header returns 401."""
    headers = get_auth_headers(client, "auth_slot@example.com")
    centre_id = create_test_centre(client, headers, "Auth Lab")

    future_dt = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    response = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_create_slot_invalid_centre(client: TestClient):
    """Creating a slot for a nonexistent centre returns 404."""
    headers = get_auth_headers(client, "missing_centre@example.com")
    future_dt = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    response = client.post(
        "/api/v1/centres/99999/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DIAGNOSTICCENTRE_NOT_FOUND"


def test_create_slot_past_datetime(client: TestClient):
    """Creating an appointment slot with a past timestamp is rejected with 422."""
    headers = get_auth_headers(client, "past_slot@example.com")
    centre_id = create_test_centre(client, headers, "Past Lab")

    past_dt = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    response = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": past_dt, "is_available": True},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAST_APPOINTMENT_DATE"


def test_create_slot_inactive_centre(client: TestClient):
    """Creating a slot at an inactive centre returns 422 INACTIVE_CENTRE."""
    headers = get_auth_headers(client, "inactive_slot@example.com")
    centre_res = client.post(
        "/api/v1/centres",
        json={"name": "Closed Lab", "address": "9 Rd", "city": "Delhi", "state": "DL", "is_active": False},
        headers=headers,
    )
    inactive_centre_id = centre_res.json()["id"]

    future_dt = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    response = client.post(
        f"/api/v1/centres/{inactive_centre_id}/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INACTIVE_CENTRE"


def test_create_slot_invalid_centre_test_id(client: TestClient):
    """Specifying a centre_test_id that doesn't belong to the centre returns 422."""
    headers = get_auth_headers(client, "test_check@example.com")
    centre_id = create_test_centre(client, headers, "Test Mismatch Lab")

    future_dt = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    response = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": future_dt, "centre_test_id": 99999},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CENTRE_TEST"


def test_create_duplicate_slot_rejected(client: TestClient):
    """Creating two slots with identical centre, datetime, and centre_test returns 409 Conflict."""
    headers = get_auth_headers(client, "dup_slot@example.com")
    centre_id = create_test_centre(client, headers, "Dup Lab")

    slot_time = (datetime.now(UTC) + timedelta(days=5)).replace(microsecond=0)
    slot_dt_str = slot_time.isoformat()

    # First slot
    res1 = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": slot_dt_str, "is_available": True},
        headers=headers,
    )
    assert res1.status_code == 201

    # Duplicate slot attempt
    res2 = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": slot_dt_str, "is_available": True},
        headers=headers,
    )
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "DUPLICATE_APPOINTMENT_SLOT"


# ── Slot Retrieval, Filtering, and Pagination Tests ───────────────────────────


def test_retrieve_slots_public(client: TestClient):
    """Listing slots for a centre does not require authentication."""
    headers = get_auth_headers(client, "retrieve_mgr@example.com")
    centre_id = create_test_centre(client, headers, "Public Lab")

    future_dt = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
        headers=headers,
    )

    # Public GET without headers
    response = client.get(f"/api/v1/centres/{centre_id}/slots")
    assert response.status_code == 200
    slots = response.json()
    assert len(slots) >= 1
    assert slots[0]["centre_id"] == centre_id


def test_filter_available_slots(client: TestClient):
    """Querying slots with is_available=true or false filters accordingly."""
    headers = get_auth_headers(client, "filter_mgr@example.com")
    centre_id = create_test_centre(client, headers, "Filter Lab")

    dt1 = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    dt2 = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    # Create one available and one unavailable slot
    client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": dt1, "is_available": True},
        headers=headers,
    )
    client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": dt2, "is_available": False},
        headers=headers,
    )

    # Filter available = true
    res_avail = client.get(f"/api/v1/centres/{centre_id}/slots?is_available=true")
    assert res_avail.status_code == 200
    avail_slots = res_avail.json()
    assert len(avail_slots) == 1
    assert avail_slots[0]["is_available"] is True

    # Filter available = false
    res_unavail = client.get(f"/api/v1/centres/{centre_id}/slots?is_available=false")
    assert res_unavail.status_code == 200
    unavail_slots = res_unavail.json()
    assert len(unavail_slots) == 1
    assert unavail_slots[0]["is_available"] is False


def test_slots_pagination(client: TestClient):
    """Slots endpoint supports skip and limit parameters."""
    headers = get_auth_headers(client, "page_mgr@example.com")
    centre_id = create_test_centre(client, headers, "Paged Lab")

    for i in range(1, 4):
        dt = (datetime.now(UTC) + timedelta(days=i)).isoformat()
        client.post(
            f"/api/v1/centres/{centre_id}/slots",
            json={"appointment_datetime": dt, "is_available": True},
            headers=headers,
        )

    # First page
    page1 = client.get(f"/api/v1/centres/{centre_id}/slots?skip=0&limit=2").json()
    assert len(page1) == 2

    # Second page
    page2 = client.get(f"/api/v1/centres/{centre_id}/slots?skip=2&limit=2").json()
    assert len(page2) == 1


def test_retrieve_slots_nonexistent_centre(client: TestClient):
    """Listing slots for a nonexistent centre returns 404."""
    response = client.get("/api/v1/centres/99999/slots")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DIAGNOSTICCENTRE_NOT_FOUND"


# ── Concurrency Row-Level Lock Reservation Test ───────────────────────────────


def test_concurrency_safe_slot_reservation(client: TestClient, db: Session):
    """Verifies slot_service.reserve_slot_concurrency_safe locks and reserves slot.

    Prepares the system for Phase 6 concurrent booking reservations:
    1. First reservation succeeds and marks is_available = False.
    2. Second reservation attempt on the same slot fails with ConflictException.
    3. Nonexistent slot raises NotFoundException.
    """
    headers = get_auth_headers(client, "lock_mgr@example.com")
    centre_id = create_test_centre(client, headers, "Lock Lab")

    future_dt = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    res = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
        headers=headers,
    )
    slot_id = res.json()["id"]

    # First reservation attempt: succeeds
    reserved_slot = slot_service.reserve_slot_concurrency_safe(db, slot_id)
    assert reserved_slot.id == slot_id
    assert reserved_slot.is_available is False

    # Second reservation attempt: raises ConflictException
    with pytest.raises(ConflictException) as exc_info:
        slot_service.reserve_slot_concurrency_safe(db, slot_id)
    assert exc_info.value.code == "SLOT_ALREADY_RESERVED"

    # Nonexistent slot: raises NotFoundException
    with pytest.raises(NotFoundException):
        slot_service.reserve_slot_concurrency_safe(db, 99999)
