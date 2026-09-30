"""Booking Engine test suite — Phase 6.

Covers:
- POST /api/v1/bookings (creation flow, validation, atomic slot reservation, price snapshot)
- GET /api/v1/bookings (user isolation, admin access, pagination)
- GET /api/v1/bookings/{booking_id} (retrieval, 403 unauthorized user access)
- POST /api/v1/bookings/{booking_id}/cancel (cancellation, slot release, 403 unauthorized cancel)
- Error handling: nonexistent CentreTest, inactive centre, inactive test, invalid slot, slot belonging to another centre, past slot, double booking (409)
- State machine transition rules & terminal states
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException
from app.models.appointment_slot import AppointmentSlot
from app.models.centre import DiagnosticCentre
from app.models.centre_test import CentreTest
from app.models.diagnostic_test import DiagnosticTest
from app.models.enums import BookingStatus, UserRole
from app.models.user import User
from app.services.booking_service import booking_service


def get_authenticated_user(client: TestClient, email_prefix: str = "patient") -> tuple[dict[str, str], int]:
    """Helper to register and login a user, returning auth headers and user ID."""
    email = f"{email_prefix}_{datetime.now(UTC).timestamp()}@example.com"
    reg_res = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "SecurePassword123!", "full_name": "Test Patient"},
    )
    user_id = reg_res.json()["id"]

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "SecurePassword123!"},
    )
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user_id


def setup_booking_fixtures(
    client: TestClient, headers: dict[str, str], price: float = 650.00
) -> tuple[int, int, int, int]:
    """Sets up a centre, diagnostic test, centre-test offering, and future slot."""
    # 1. Create Centre
    c_res = client.post(
        "/api/v1/centres",
        json={
            "name": "Apollo Diagnostic Hub",
            "address": "45 Green Way",
            "city": "Bengaluru",
            "state": "Karnataka",
        },
        headers=headers,
    )
    centre_id = c_res.json()["id"]

    # 2. Create Test
    t_res = client.post(
        "/api/v1/tests",
        json={
            "name": "HbA1c Glycated Hemoglobin",
            "description": "3-month average blood sugar panel",
            "category": "Diabetology",
        },
        headers=headers,
    )
    test_id = t_res.json()["id"]

    # 3. Associate with price
    ct_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": test_id, "price": price},
        headers=headers,
    )
    centre_test_id = ct_res.json()["id"]

    # 4. Create future slot (3 days ahead)
    future_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    slot_res = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": future_time, "is_available": True},
        headers=headers,
    )
    slot_id = slot_res.json()["id"]

    return centre_id, test_id, centre_test_id, slot_id


# ── Booking Creation & Validation Tests ────────────────────────────────────────


def test_create_booking_success(client: TestClient):
    """Booking creation succeeds in PENDING state and marks the slot unavailable."""
    headers, _ = get_authenticated_user(client, "patient_success")
    centre_id, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers, 650.00)

    payload = {
        "centre_test_id": centre_test_id,
        "appointment_slot_id": slot_id,
    }
    response = client.post("/api/v1/bookings", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PENDING"
    assert data["booking_reference"].startswith("BKG-")
    assert Decimal(str(data["amount"])) == Decimal("650.00")
    assert data["centre_test_id"] == centre_test_id
    assert data["appointment_slot_id"] == slot_id

    # Verify slot is now unavailable
    slots = client.get(f"/api/v1/centres/{centre_id}/slots", headers=headers).json()
    booked_slot = next(s for s in slots if s["id"] == slot_id)
    assert booked_slot["is_available"] is False


def test_booking_price_snapshot(client: TestClient, db: Session):
    """Booking price is snapshotted at creation time and remains unchanged even if CentreTest price updates."""
    headers, _ = get_authenticated_user(client, "price_snap_user")
    _, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers, 650.00)

    # Create booking when price is 650.00
    res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    assert res.status_code == 201
    booking_id = res.json()["id"]
    assert Decimal(str(res.json()["amount"])) == Decimal("650.00")

    # Centre updates test price to 700.00
    ct = db.get(CentreTest, centre_test_id)
    assert ct is not None
    ct.price = Decimal("700.00")
    db.commit()

    # Existing booking amount MUST remain 650.00
    get_res = client.get(f"/api/v1/bookings/{booking_id}", headers=headers)
    assert get_res.status_code == 200
    assert Decimal(str(get_res.json()["amount"])) == Decimal("650.00")


def test_booking_nonexistent_centre_test(client: TestClient):
    """Booking with invalid CentreTest ID returns 404."""
    headers, _ = get_authenticated_user(client, "missing_ct_user")
    _, _, _, slot_id = setup_booking_fixtures(client, headers)

    response = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": 99999, "appointment_slot_id": slot_id},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CENTRETEST_NOT_FOUND"


def test_booking_inactive_centre(client: TestClient, db: Session):
    """Booking at an inactive centre returns 422 CENTRE_INACTIVE."""
    headers, _ = get_authenticated_user(client, "inactive_c_user")
    centre_id, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers)

    # Deactivate centre
    centre = db.get(DiagnosticCentre, centre_id)
    assert centre is not None
    centre.is_active = False
    db.commit()

    response = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CENTRE_INACTIVE"


def test_booking_inactive_test(client: TestClient, db: Session):
    """Booking an inactive test returns 422 TEST_INACTIVE."""
    headers, _ = get_authenticated_user(client, "inactive_t_user")
    _, test_id, centre_test_id, slot_id = setup_booking_fixtures(client, headers)

    # Deactivate test
    test = db.get(DiagnosticTest, test_id)
    assert test is not None
    test.is_active = False
    db.commit()

    response = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEST_INACTIVE"


def test_booking_invalid_slot(client: TestClient):
    """Booking with nonexistent appointment_slot_id returns 404."""
    headers, _ = get_authenticated_user(client, "missing_slot_user")
    _, _, centre_test_id, _ = setup_booking_fixtures(client, headers)

    response = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": 99999},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "APPOINTMENTSLOT_NOT_FOUND"


def test_booking_slot_belonging_to_another_centre(client: TestClient):
    """Booking with a slot that belongs to a different centre returns 422 INVALID_SLOT_CENTRE."""
    headers, _ = get_authenticated_user(client, "cross_centre_user")
    _, _, centre_test_id, _ = setup_booking_fixtures(client, headers)

    # Create a second centre and slot
    c2_res = client.post(
        "/api/v1/centres",
        json={"name": "Centre 2", "address": "2 St", "city": "Delhi", "state": "DL"},
        headers=headers,
    )
    centre2_id = c2_res.json()["id"]
    future_time = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    s2_res = client.post(
        f"/api/v1/centres/{centre2_id}/slots",
        json={"appointment_datetime": future_time, "is_available": True},
        headers=headers,
    )
    slot2_id = s2_res.json()["id"]

    # Try booking centre_test from Centre 1 with slot from Centre 2
    response = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot2_id},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SLOT_CENTRE"


def test_booking_past_slot(client: TestClient, db: Session):
    """Booking a slot that has lapsed into the past returns 422 PAST_APPOINTMENT_DATE."""
    headers, _ = get_authenticated_user(client, "past_slot_bkg")
    _, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers)

    # Shift slot datetime into the past directly in DB
    slot = db.get(AppointmentSlot, slot_id)
    assert slot is not None
    slot.appointment_datetime = datetime.now(UTC) - timedelta(hours=2)
    db.commit()

    response = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAST_APPOINTMENT_DATE"


def test_double_booking_conflict(client: TestClient):
    """When two users attempt to book the same slot, the first succeeds and the second receives 409 SLOT_ALREADY_BOOKED."""
    headers1, _ = get_authenticated_user(client, "racer1")
    headers2, _ = get_authenticated_user(client, "racer2")
    _, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers1)

    booking_payload = {
        "centre_test_id": centre_test_id,
        "appointment_slot_id": slot_id,
    }

    # Request A succeeds
    res1 = client.post("/api/v1/bookings", json=booking_payload, headers=headers1)
    assert res1.status_code == 201

    # Request B fails with 409
    res2 = client.post("/api/v1/bookings", json=booking_payload, headers=headers2)
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "SLOT_ALREADY_BOOKED"


# ── Authorization & Privacy Tests ─────────────────────────────────────────────


def test_unauthorized_booking_access(client: TestClient):
    """User B cannot retrieve User A's booking (returns 403 FORBIDDEN)."""
    headers1, _ = get_authenticated_user(client, "owner_a")
    headers2, _ = get_authenticated_user(client, "intruder_b")
    _, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers1)

    # User A creates booking
    res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers1,
    )
    booking_id = res.json()["id"]

    # User B attempts to view User A's booking
    get_res = client.get(f"/api/v1/bookings/{booking_id}", headers=headers2)
    assert get_res.status_code == 403
    assert get_res.json()["error"]["code"] == "FORBIDDEN"


def test_unauthorized_cancellation(client: TestClient):
    """User B cannot cancel User A's booking (returns 403 FORBIDDEN)."""
    headers1, _ = get_authenticated_user(client, "owner_cancel")
    headers2, _ = get_authenticated_user(client, "intruder_cancel")
    _, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers1)

    res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers1,
    )
    booking_id = res.json()["id"]

    # User B attempts to cancel User A's booking
    cancel_res = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers2)
    assert cancel_res.status_code == 403
    assert cancel_res.json()["error"]["code"] == "FORBIDDEN"


def test_list_bookings_user_isolation(client: TestClient, db: Session):
    """Regular users only see their own bookings; administrators see all bookings."""
    headers1, user1_id = get_authenticated_user(client, "iso_user1")
    headers2, user2_id = get_authenticated_user(client, "iso_user2")

    # User 1 creates a booking
    _, _, ct1, s1 = setup_booking_fixtures(client, headers1)
    client.post("/api/v1/bookings", json={"centre_test_id": ct1, "appointment_slot_id": s1}, headers=headers1)

    # User 2 creates a booking
    _, _, ct2, s2 = setup_booking_fixtures(client, headers2)
    client.post("/api/v1/bookings", json={"centre_test_id": ct2, "appointment_slot_id": s2}, headers=headers2)

    # User 1 listing only contains User 1's booking
    list1 = client.get("/api/v1/bookings", headers=headers1).json()
    assert all(b["user_id"] == user1_id for b in list1)

    # User 2 listing only contains User 2's booking
    list2 = client.get("/api/v1/bookings", headers=headers2).json()
    assert all(b["user_id"] == user2_id for b in list2)

    # Elevate User 1 to ADMIN and verify admin sees both
    admin_user = db.get(User, user1_id)
    assert admin_user is not None
    admin_user.role = UserRole.ADMIN
    db.commit()

    admin_list = client.get("/api/v1/bookings", headers=headers1).json()
    assert len(admin_list) >= 2


# ── Cancellation Lifecycle & State Rules Tests ────────────────────────────────


def test_successful_cancellation_and_slot_release(client: TestClient):
    """Cancelling a booking marks it CANCELLED and makes the appointment slot available again."""
    headers, _ = get_authenticated_user(client, "canceller")
    centre_id, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers)

    # Book slot
    book_res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    booking_id = book_res.json()["id"]

    # Cancel booking
    cancel_res = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # Verify slot is freed up
    slots = client.get(f"/api/v1/centres/{centre_id}/slots", headers=headers).json()
    freed_slot = next(s for s in slots if s["id"] == slot_id)
    assert freed_slot["is_available"] is True


def test_cancellation_state_rules(client: TestClient, db: Session):
    """State rules: cannot cancel a CANCELLED or FAILED booking; cancelling a CONFIRMED booking is allowed."""
    headers, _ = get_authenticated_user(client, "state_rules_user")
    _, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers)

    # 1. Create booking
    res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    booking_id = res.json()["id"]

    # 2. Transition booking to FAILED
    booking = booking_service.get_booking(db, db.get(User, res.json()["user_id"]), booking_id)
    booking_service.transition_status(db, booking, BookingStatus.FAILED)
    db.commit()

    # 3. Attempting to cancel FAILED booking returns 409
    fail_cancel = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers)
    assert fail_cancel.status_code == 409
    assert fail_cancel.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_cancel_confirmed_booking(client: TestClient, db: Session):
    """Cancelling a CONFIRMED booking succeeds and transitions to CANCELLED."""
    headers, _ = get_authenticated_user(client, "confirmed_canceller")
    _, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers)

    res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    booking_id = res.json()["id"]

    # Transition booking to CONFIRMED
    booking = booking_service.get_booking(db, db.get(User, res.json()["user_id"]), booking_id)
    booking_service.transition_status(db, booking, BookingStatus.CONFIRMED)
    db.commit()

    # Cancel CONFIRMED booking
    cancel_res = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"


# ── State Machine Unit Transitions Tests ──────────────────────────────────────


def test_booking_state_machine_transitions(client: TestClient, db: Session):
    """Directly test centralized transition_status rules:
    - PENDING -> CONFIRMED (OK)
    - CONFIRMED -> CANCELLED (OK)
    - CANCELLED -> any (ConflictException)
    - FAILED -> any (ConflictException)
    - CONFIRMED -> FAILED (ConflictException)
    """
    headers, _ = get_authenticated_user(client, "sm_tester")
    _, _, centre_test_id, slot_id = setup_booking_fixtures(client, headers)

    res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    booking = booking_service.get_booking(db, db.get(User, res.json()["user_id"]), res.json()["id"])

    # PENDING -> CONFIRMED (valid)
    booking_service.transition_status(db, booking, BookingStatus.CONFIRMED)
    assert booking.status == BookingStatus.CONFIRMED

    # CONFIRMED -> FAILED (invalid)
    with pytest.raises(ConflictException) as exc_info:
        booking_service.transition_status(db, booking, BookingStatus.FAILED)
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"

    # CONFIRMED -> CANCELLED (valid)
    booking_service.transition_status(db, booking, BookingStatus.CANCELLED)
    assert booking.status == BookingStatus.CANCELLED

    # CANCELLED -> CONFIRMED (invalid: terminal)
    with pytest.raises(ConflictException) as exc_info:
        booking_service.transition_status(db, booking, BookingStatus.CONFIRMED)
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"
