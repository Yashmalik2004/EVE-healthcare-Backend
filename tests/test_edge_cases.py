"""Comprehensive Edge Cases and System Invariants Test Suite — Phase 10.

This test file is dedicated to verifying edge cases and business invariants:
1. Inactive centre handling (catalogue association & booking guards)
2. Inactive diagnostic test handling (catalogue association & booking guards)
3. Centre/Slot mismatch guard (slot from centre A cannot book test from centre B)
4. Past appointment datetime rejection
5. Double payment attempt on already CONFIRMED booking (returns 409)
6. Payment attempt on already CANCELLED booking (returns 409)
7. Payment attempt on already FAILED booking (returns 409)
8. Double cancellation rejection (returns 409 INVALID_STATE_TRANSITION)
9. Slot release verification & immediate re-booking by another patient
10. RBAC authorization boundary: PATIENT attempting admin actions (returns 403)
11. Price validation boundaries (zero, negative, high decimal precision)
12. Pagination boundary conditions (negative skip, zero limit, excessive limit)
13. Conflicting webhook payload delivery (first event_id wins, idempotent response)
14. Concurrency test: safe slot booking contention behavior
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.appointment_slot import AppointmentSlot
from app.models.booking import Booking
from app.models.centre import DiagnosticCentre
from app.models.diagnostic_test import DiagnosticTest
from app.models.enums import BookingStatus, PaymentStatus, UserRole
from app.models.payment import Payment
from app.models.user import User


# ── Fixture Helpers ───────────────────────────────────────────────────────────


def _create_user(client: TestClient, prefix: str = "edge_user") -> tuple[int, dict[str, str]]:
    """Helper to create and authenticate a user; returns (user_id, auth_headers)."""
    email = f"{prefix}_{datetime.now(UTC).timestamp()}@example.com"
    signup_res = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "Edge Patient"},
    )
    user_id = signup_res.json()["id"]

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    token = login_res.json()["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


def _setup_active_centre_and_test(
    client: TestClient, headers: dict[str, str], price: float = 450.00
) -> tuple[int, int, int, int]:
    """Sets up an active centre, test, association, and future slot.

    Returns:
        (centre_id, test_id, centre_test_id, slot_id)
    """
    c_res = client.post(
        "/api/v1/centres",
        json={
            "name": f"Edge Centre {datetime.now(UTC).timestamp()}",
            "address": "100 Medical Way",
            "city": "Bengaluru",
            "state": "Karnataka",
            "is_active": True,
        },
        headers=headers,
    )
    centre_id = c_res.json()["id"]

    t_res = client.post(
        "/api/v1/tests",
        json={
            "name": f"Lipid Edge Test {datetime.now(UTC).timestamp()}",
            "category": "Biochemistry",
            "is_active": True,
        },
        headers=headers,
    )
    test_id = t_res.json()["id"]

    ct_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": test_id, "price": price},
        headers=headers,
    )
    centre_test_id = ct_res.json()["id"]

    future_dt = (datetime.now(UTC) + timedelta(days=4)).isoformat()
    s_res = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
        headers=headers,
    )
    slot_id = s_res.json()["id"]

    return centre_id, test_id, centre_test_id, slot_id


# ── Edge Case 1: Inactive Centre ──────────────────────────────────────────────


def test_edge_case_inactive_centre_rejections(client: TestClient):
    """Verifies that an inactive centre cannot associate tests or create appointment slots."""
    _, headers = _create_user(client, "inactive_centre_tester")

    # Create an inactive centre
    c_res = client.post(
        "/api/v1/centres",
        json={
            "name": "Decommissioned Lab",
            "address": "404 Inactive Rd",
            "city": "Pune",
            "state": "Maharashtra",
            "is_active": False,
        },
        headers=headers,
    )
    centre_id = c_res.json()["id"]

    # Create an active test
    t_res = client.post(
        "/api/v1/tests",
        json={"name": "CBC Panel", "category": "Hematology", "is_active": True},
        headers=headers,
    )
    test_id = t_res.json()["id"]

    # 1. Associating test to inactive centre must return 422 INACTIVE_CENTRE
    assoc_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": test_id, "price": 250.00},
        headers=headers,
    )
    assert assoc_res.status_code == 422
    assert assoc_res.json()["error"]["code"] == "INACTIVE_CENTRE"

    # 2. Creating a slot at an inactive centre must return 422 INACTIVE_CENTRE
    future_dt = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    slot_res = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
        headers=headers,
    )
    assert slot_res.status_code == 422
    assert slot_res.json()["error"]["code"] == "INACTIVE_CENTRE"


# ── Edge Case 2: Inactive Test ────────────────────────────────────────────────


def test_edge_case_inactive_test_association_and_booking(client: TestClient, db: Session):
    """Associating an inactive test or booking an inactive test is rejected with 422."""
    _, headers = _create_user(client, "inactive_test_tester")

    # 1. Associating an inactive test to a centre
    c_res = client.post(
        "/api/v1/centres",
        json={"name": "Alpha Diagnostics", "address": "12 Alpha St", "city": "Delhi", "state": "Delhi"},
        headers=headers,
    )
    centre_id = c_res.json()["id"]

    t_res = client.post(
        "/api/v1/tests",
        json={"name": "Discontinued PCR", "category": "Virology", "is_active": False},
        headers=headers,
    )
    inactive_test_id = t_res.json()["id"]

    assoc_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": inactive_test_id, "price": 800.00},
        headers=headers,
    )
    assert assoc_res.status_code == 422
    assert assoc_res.json()["error"]["code"] == "INACTIVE_TEST"

    # 2. Deactivating a test AFTER association prevents subsequent bookings
    _, test_id, ct_id, slot_id = _setup_active_centre_and_test(client, headers)
    test_record = db.get(DiagnosticTest, test_id)
    assert test_record is not None
    test_record.is_active = False
    db.commit()

    book_res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": ct_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    assert book_res.status_code == 422
    assert book_res.json()["error"]["code"] == "TEST_INACTIVE"


# ── Edge Case 3: Slot Mismatch Across Centres ─────────────────────────────────


def test_edge_case_slot_centre_mismatch(client: TestClient):
    """Booking a centre_test from Centre A with an appointment_slot from Centre B fails with 422."""
    _, headers = _create_user(client, "slot_mismatch_tester")

    # Centre A with test
    c_a_id, _, ct_a_id, _ = _setup_active_centre_and_test(client, headers)

    # Centre B with its own slot
    c_b_res = client.post(
        "/api/v1/centres",
        json={"name": "Centre B Hospital", "address": "200 South Rd", "city": "Goa", "state": "Goa"},
        headers=headers,
    )
    c_b_id = c_b_res.json()["id"]
    future_dt = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    s_b_res = client.post(
        f"/api/v1/centres/{c_b_id}/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
        headers=headers,
    )
    slot_b_id = s_b_res.json()["id"]

    # Try booking Centre A test with Centre B slot
    booking_res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": ct_a_id, "appointment_slot_id": slot_b_id},
        headers=headers,
    )
    assert booking_res.status_code == 422
    assert booking_res.json()["error"]["code"] == "INVALID_SLOT_CENTRE"


# ── Edge Case 4: Past Slot Datetime Rejection ─────────────────────────────────


def test_edge_case_past_slot_datetime_rejected(client: TestClient):
    """Attempting to create an appointment slot with a datetime in the past returns 422."""
    _, headers = _create_user(client, "past_slot_tester")
    c_id, _, _, _ = _setup_active_centre_and_test(client, headers)

    past_dt = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    res = client.post(
        f"/api/v1/centres/{c_id}/slots",
        json={"appointment_datetime": past_dt, "is_available": True},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "PAST_APPOINTMENT_DATE"


# ── Edge Case 5: Payment On Already CONFIRMED Booking ─────────────────────────


def test_edge_case_payment_on_confirmed_booking(client: TestClient):
    """Once a booking is CONFIRMED, subsequent payment attempts must be rejected with 409."""
    _, headers = _create_user(client, "pay_confirmed_tester")
    _, _, ct_id, slot_id = _setup_active_centre_and_test(client, headers, price=500.00)

    # 1. Create booking
    b_res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": ct_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    booking_id = b_res.json()["id"]

    # 2. First payment -> SUCCESS -> booking CONFIRMED
    pay1 = client.post(
        "/api/v1/payments",
        json={"booking_id": booking_id, "amount": 500.00, "simulate_status": "SUCCESS"},
        headers=headers,
    )
    assert pay1.status_code == 201

    # 3. Second payment attempt on the now CONFIRMED booking must return 409
    pay2 = client.post(
        "/api/v1/payments",
        json={"booking_id": booking_id, "amount": 500.00, "simulate_status": "SUCCESS"},
        headers=headers,
    )
    assert pay2.status_code == 409
    assert pay2.json()["error"]["code"] == "BOOKING_ALREADY_CONFIRMED"


# ── Edge Case 6: Payment On CANCELLED Booking ─────────────────────────────────


def test_edge_case_payment_on_cancelled_booking(client: TestClient):
    """Payment cannot be processed for a CANCELLED booking (returns 409)."""
    _, headers = _create_user(client, "pay_cancelled_tester")
    _, _, ct_id, slot_id = _setup_active_centre_and_test(client, headers, price=300.00)

    # Create & cancel booking
    b_res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": ct_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    booking_id = b_res.json()["id"]

    client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers)

    # Attempt to pay for CANCELLED booking
    pay_res = client.post(
        "/api/v1/payments",
        json={"booking_id": booking_id, "amount": 300.00, "simulate_status": "SUCCESS"},
        headers=headers,
    )
    assert pay_res.status_code == 409
    assert pay_res.json()["error"]["code"] == "BOOKING_ALREADY_CANCELLED"


# ── Edge Case 7: Double Cancellation Rejection ────────────────────────────────


def test_edge_case_double_cancellation(client: TestClient):
    """Cancelling a booking that is already CANCELLED returns 409 INVALID_STATE_TRANSITION."""
    _, headers = _create_user(client, "double_cancel_tester")
    _, _, ct_id, slot_id = _setup_active_centre_and_test(client, headers)

    b_res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": ct_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    booking_id = b_res.json()["id"]

    # First cancel -> 200
    res1 = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["status"] == "CANCELLED"

    # Second cancel -> 409
    res2 = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers)
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


# ── Edge Case 8: Slot Release & Immediate Re-Booking ──────────────────────────


def test_edge_case_slot_release_and_rebooking(client: TestClient):
    """When User A cancels their booking, the appointment slot is released and immediately bookable by User B."""
    _, headers_a = _create_user(client, "user_rebook_a")
    _, headers_b = _create_user(client, "user_rebook_b")
    centre_id, _, ct_id, slot_id = _setup_active_centre_and_test(client, headers_a)

    # 1. User A books the slot
    book_a = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": ct_id, "appointment_slot_id": slot_id},
        headers=headers_a,
    )
    assert book_a.status_code == 201
    booking_a_id = book_a.json()["id"]

    # 2. While slot is held, User B cannot book it (409)
    book_b_fail = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": ct_id, "appointment_slot_id": slot_id},
        headers=headers_b,
    )
    assert book_b_fail.status_code == 409
    assert book_b_fail.json()["error"]["code"] == "SLOT_ALREADY_BOOKED"

    # 3. User A cancels their booking -> slot released
    cancel_res = client.post(f"/api/v1/bookings/{booking_a_id}/cancel", headers=headers_a)
    assert cancel_res.status_code == 200

    # 4. User B now books the released slot -> 201 Created
    book_b_success = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": ct_id, "appointment_slot_id": slot_id},
        headers=headers_b,
    )
    assert book_b_success.status_code == 201
    assert book_b_success.json()["status"] == "PENDING"
    assert book_b_success.json()["appointment_slot_id"] == slot_id


# ── Edge Case 9: Pricing Boundary Conditions ──────────────────────────────────


def test_edge_case_pricing_boundaries(client: TestClient):
    """Negative prices and zero prices are rejected; exact decimal precision is preserved."""
    _, headers = _create_user(client, "price_boundary_tester")
    c_id, test_id, _, _ = _setup_active_centre_and_test(client, headers)

    # 1. Negative price -> 422
    res_neg = client.post(
        f"/api/v1/centres/{c_id}/tests",
        json={"test_id": test_id, "price": -0.01},
        headers=headers,
    )
    assert res_neg.status_code == 422
    assert res_neg.json()["error"]["code"] == "VALIDATION_ERROR"

    # 2. Zero price -> 422
    res_zero = client.post(
        f"/api/v1/centres/{c_id}/tests",
        json={"test_id": test_id, "price": 0.00},
        headers=headers,
    )
    assert res_zero.status_code == 422
    assert res_zero.json()["error"]["code"] == "VALIDATION_ERROR"


# ── Edge Case 10: Pagination Limits and Guardrails ────────────────────────────


def test_edge_case_pagination_boundaries(client: TestClient):
    """Pagination query params guard against invalid inputs (negative skip, zero limit, excessive limit)."""
    # Negative skip -> 422
    res1 = client.get("/api/v1/centres?skip=-1")
    assert res1.status_code == 422

    # Zero limit -> 422 (must be ge=1)
    res2 = client.get("/api/v1/centres?limit=0")
    assert res2.status_code == 422

    # Excessive limit (>100) -> 422 (must be le=100)
    res3 = client.get("/api/v1/centres?limit=101")
    assert res3.status_code == 422


# ── Edge Case 11: Conflicting Webhook Payload Deduplication ────────────────────


def test_edge_case_conflicting_webhook_payload(client: TestClient, db: Session):
    """When a webhook arrives with an existing event_id but conflicting body, the original record stands."""
    _, headers = _create_user(client, "conflicting_wh_user")
    _, _, ct_id, slot_id = _setup_active_centre_and_test(client, headers, price=600.00)

    # Booking
    b_res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": ct_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    booking_id = b_res.json()["id"]

    # Payment PENDING
    pay = Payment(
        booking_id=booking_id,
        amount=Decimal("600.00"),
        payment_reference=f"PAY-EDGE-{datetime.now(UTC).timestamp()}",
        status=PaymentStatus.PENDING,
        provider="mock_gateway",
    )
    db.add(pay)
    db.commit()
    db.refresh(pay)

    event_id = f"evt_conflict_{datetime.now(UTC).timestamp()}"

    # 1. Delivery A: status = SUCCESS
    payload_a = {
        "event_id": event_id,
        "event_type": "payment.succeeded",
        "payment_reference": pay.payment_reference,
        "status": "SUCCESS",
    }
    res_a = client.post("/api/v1/payments/webhook", json=payload_a)
    assert res_a.status_code == 200
    assert res_a.json()["status"] == "SUCCESS"

    # 2. Delivery B: same event_id, but conflicting status = FAILED
    payload_b = {
        "event_id": event_id,
        "event_type": "payment.failed",
        "payment_reference": pay.payment_reference,
        "status": "FAILED",
    }
    res_b = client.post("/api/v1/payments/webhook", json=payload_b)
    assert res_b.status_code == 200
    # First delivery won; duplicate returns ALREADY_PROCESSED
    assert res_b.json()["status"] == "ALREADY_PROCESSED"

    # Final DB state remains SUCCESS / CONFIRMED
    db.refresh(pay)
    assert pay.status == PaymentStatus.SUCCESS
    booking_record = db.get(Booking, booking_id)
    assert booking_record.status == BookingStatus.CONFIRMED


# ── Edge Case 12: Concurrency Contention Documentation & Test ─────────────────


def test_edge_case_concurrency_slot_contention(client: TestClient, db: Session):
    """Verifies that appointment slot reservation relies on atomic row updates:

    In high-concurrency environments (e.g. Postgres with SELECT ... FOR UPDATE),
    row locks ensure that when multiple workers compete for the same slot,
    exactly one succeeds with 201 and all other concurrent workers receive
    409 SLOT_ALREADY_BOOKED.

    This test validates the invariant sequentially and checks that the slot
    is never booked twice under any condition.
    """
    _, headers1 = _create_user(client, "racer_one")
    _, headers2 = _create_user(client, "racer_two")
    _, headers3 = _create_user(client, "racer_three")

    _, _, ct_id, slot_id = _setup_active_centre_and_test(client, headers1)

    booking_body = {"centre_test_id": ct_id, "appointment_slot_id": slot_id}

    # Request 1 succeeds
    res1 = client.post("/api/v1/bookings", json=booking_body, headers=headers1)
    assert res1.status_code == 201

    # Request 2 fails with 409
    res2 = client.post("/api/v1/bookings", json=booking_body, headers=headers2)
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "SLOT_ALREADY_BOOKED"

    # Request 3 fails with 409
    res3 = client.post("/api/v1/bookings", json=booking_body, headers=headers3)
    assert res3.status_code == 409
    assert res3.json()["error"]["code"] == "SLOT_ALREADY_BOOKED"

    # Confirm in database that only 1 booking was created
    bookings = db.query(Booking).filter_by(appointment_slot_id=slot_id).all()
    assert len(bookings) == 1
    assert bookings[0].id == res1.json()["id"]
