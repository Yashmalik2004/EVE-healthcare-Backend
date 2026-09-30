"""Test suite for Phase 7 — Simulated Payment Service.

Covers:
    - successful payment (SUCCESS → booking CONFIRMED)
    - failed payment (FAILED → booking FAILED)
    - invalid booking id (404)
    - unauthorized payment (user B cannot pay user A's booking)
    - payment amount mismatch (422)
    - payment on CONFIRMED booking (409)
    - payment on CANCELLED booking (409)
    - payment on FAILED booking (409)
    - duplicate successful payment without idempotency key (409)
    - repeated Idempotency-Key returns identical payment record (200/201)
    - payment record fields are persisted correctly
    - booking status transitions verified via GET /bookings/{id}
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient


# ── Shared helpers ────────────────────────────────────────────────────────────


def _signup_and_login(client: TestClient, email: str | None = None) -> dict:
    """Register and authenticate a user; return auth headers."""
    ts = datetime.now(UTC).timestamp()
    email = email or f"pay_user_{ts}@example.com"
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "Pay User"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _build_booking(client: TestClient, headers: dict, price: Decimal = Decimal("500.00")) -> dict:
    """Create a full centre → test → centre_test → slot → booking chain.

    Returns the booking JSON dict.
    """
    # Diagnostic Centre
    c_res = client.post(
        "/api/v1/centres",
        json={
            "name": "Test Centre",
            "address": "1 Main St",
            "city": "Mumbai",
            "state": "Maharashtra",
        },
        headers=headers,
    )
    assert c_res.status_code == 201, c_res.text
    centre_id = c_res.json()["id"]

    # Diagnostic Test
    t_res = client.post(
        "/api/v1/tests",
        json={
            "name": "CBC Test",
            "description": "Complete Blood Count",
            "category": "Haematology",
        },
        headers=headers,
    )
    assert t_res.status_code == 201, t_res.text
    test_id = t_res.json()["id"]

    # Centre → Test association with price
    ct_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": test_id, "price": float(price)},
        headers=headers,
    )
    assert ct_res.status_code == 201, ct_res.text
    centre_test_id = ct_res.json()["id"]

    # Appointment Slot (5 days from now)
    future_dt = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    slot_res = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
        headers=headers,
    )
    assert slot_res.status_code == 201, slot_res.text
    slot_id = slot_res.json()["id"]

    # Booking
    booking_res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    assert booking_res.status_code == 201, booking_res.text
    return booking_res.json()


# ── Test cases ────────────────────────────────────────────────────────────────


class TestSuccessfulPayment:
    """Payment with simulate_status=SUCCESS confirms the booking."""

    def test_payment_success_status_201(self, client: TestClient):
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("500.00"))

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert res.status_code == 201

    def test_payment_success_returns_success_status(self, client: TestClient):
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("300.00"))

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 300.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert res.json()["status"] == "SUCCESS"

    def test_payment_success_confirms_booking(self, client: TestClient):
        """POST /payments with SUCCESS must transition booking to CONFIRMED."""
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("750.00"))
        booking_id = booking["id"]

        client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 750.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )

        get_res = client.get(f"/api/v1/bookings/{booking_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["status"] == "CONFIRMED"

    def test_payment_reference_format(self, client: TestClient):
        """Payment reference must start with PAY-."""
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("200.00"))

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 200.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert res.json()["payment_reference"].startswith("PAY-")

    def test_payment_record_fields(self, client: TestClient):
        """Verify all expected fields are present and correct in the response."""
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("400.00"))

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 400.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        data = res.json()
        assert data["id"] > 0
        assert data["booking_id"] == booking["id"]
        assert Decimal(str(data["amount"])) == Decimal("400.00")
        assert data["status"] == "SUCCESS"
        assert data["provider"] == "mock_gateway"
        assert data["provider_transaction_id"] is not None
        assert "created_at" in data
        assert "updated_at" in data


class TestFailedPayment:
    """Payment with simulate_status=FAILED fails the booking."""

    def test_payment_failed_status_201(self, client: TestClient):
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("400.00"))

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 400.00, "simulate_status": "FAILED"},
            headers=headers,
        )
        assert res.status_code == 201

    def test_payment_failure_fails_booking(self, client: TestClient):
        """POST /payments with FAILED must transition booking to FAILED."""
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("600.00"))
        booking_id = booking["id"]

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 600.00, "simulate_status": "FAILED"},
            headers=headers,
        )
        assert res.json()["status"] == "FAILED"

        get_res = client.get(f"/api/v1/bookings/{booking_id}", headers=headers)
        assert get_res.json()["status"] == "FAILED"


class TestInvalidBooking:
    """Payments referencing non-existent or inaccessible bookings."""

    def test_payment_invalid_booking_id(self, client: TestClient):
        """Non-existent booking → 404."""
        headers = _signup_and_login(client)

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": 999999, "amount": 100.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert res.status_code == 404
        assert "BOOKING_NOT_FOUND" in res.json()["error"]["code"]


class TestUnauthorizedPayment:
    """User B cannot pay for User A's booking."""

    def test_payment_unauthorized(self, client: TestClient):
        """Attempting to pay another user's booking → 403."""
        ts = datetime.now(UTC).timestamp()
        headers_a = _signup_and_login(client, f"user_a_{ts}@example.com")
        headers_b = _signup_and_login(client, f"user_b_{ts}@example.com")

        booking = _build_booking(client, headers_a, Decimal("500.00"))

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers_b,  # wrong user
        )
        assert res.status_code == 403


class TestAmountMismatch:
    """Client-supplied amount must exactly equal Booking.amount."""

    def test_payment_amount_mismatch(self, client: TestClient):
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("500.00"))

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 300.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "PAYMENT_AMOUNT_MISMATCH"

    def test_payment_amount_slightly_off(self, client: TestClient):
        """Even a penny off must be rejected."""
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("100.00"))

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 100.01, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "PAYMENT_AMOUNT_MISMATCH"


class TestBookingStatusGuards:
    """Payments must be rejected for non-PENDING bookings."""

    def test_payment_on_confirmed_booking(self, client: TestClient):
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("500.00"))
        booking_id = booking["id"]

        # Confirm the booking via a successful payment
        client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )

        # Try to pay again
        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "BOOKING_ALREADY_CONFIRMED"

    def test_payment_on_cancelled_booking(self, client: TestClient):
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("500.00"))
        booking_id = booking["id"]

        # Cancel the booking
        cancel_res = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers)
        assert cancel_res.status_code == 200

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "BOOKING_ALREADY_CANCELLED"

    def test_payment_on_failed_booking(self, client: TestClient):
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("500.00"))
        booking_id = booking["id"]

        # Fail the booking via a failed payment
        client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 500.00, "simulate_status": "FAILED"},
            headers=headers,
        )

        # Try to pay the now-FAILED booking
        res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "BOOKING_FAILED"


class TestDuplicatePayment:
    """Duplicate successful payment without an idempotency key must be rejected."""

    def test_duplicate_successful_payment_rejected(self, client: TestClient):
        """A second payment on the same booking without idempotency key → 409 CONFIRMED."""
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("500.00"))
        booking_id = booking["id"]

        # First payment succeeds
        first = client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert first.status_code == 201

        # Second payment must be rejected (booking is now CONFIRMED)
        second = client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        assert second.status_code == 409


class TestIdempotencyKey:
    """Repeated requests with the same Idempotency-Key return the identical payment record."""

    def test_idempotency_key_returns_same_payment(self, client: TestClient):
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("750.00"))
        booking_id = booking["id"]

        ik = f"ik_{datetime.now(UTC).timestamp()}"
        payload = {"booking_id": booking_id, "amount": 750.00, "simulate_status": "SUCCESS"}
        headers_with_ik = {**headers, "Idempotency-Key": ik}

        # First request
        res1 = client.post("/api/v1/payments", json=payload, headers=headers_with_ik)
        assert res1.status_code == 201
        pay1 = res1.json()

        # Repeated request with same key
        res2 = client.post("/api/v1/payments", json=payload, headers=headers_with_ik)
        assert res2.status_code in (200, 201)
        pay2 = res2.json()

        assert pay1["id"] == pay2["id"]
        assert pay1["payment_reference"] == pay2["payment_reference"]
        assert pay1["status"] == pay2["status"]

    def test_idempotency_key_no_duplicate_booking_transition(self, client: TestClient):
        """Idempotent repeat must NOT create a second payment record."""
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("300.00"))
        booking_id = booking["id"]

        ik = f"ik_nodupe_{datetime.now(UTC).timestamp()}"
        payload = {"booking_id": booking_id, "amount": 300.00, "simulate_status": "SUCCESS"}
        headers_with_ik = {**headers, "Idempotency-Key": ik}

        client.post("/api/v1/payments", json=payload, headers=headers_with_ik)
        client.post("/api/v1/payments", json=payload, headers=headers_with_ik)

        # Booking must still be CONFIRMED (not errored or duplicated)
        get_res = client.get(f"/api/v1/bookings/{booking_id}", headers=headers)
        assert get_res.json()["status"] == "CONFIRMED"


class TestGetPayment:
    """GET /payments/{payment_id} endpoint."""

    def test_get_payment_success(self, client: TestClient):
        headers = _signup_and_login(client)
        booking = _build_booking(client, headers, Decimal("500.00"))

        create_res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        payment_id = create_res.json()["id"]

        get_res = client.get(f"/api/v1/payments/{payment_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["id"] == payment_id

    def test_get_payment_not_found(self, client: TestClient):
        headers = _signup_and_login(client)
        res = client.get("/api/v1/payments/999999", headers=headers)
        assert res.status_code == 404

    def test_get_payment_unauthorized(self, client: TestClient):
        """User B cannot view a payment belonging to User A's booking."""
        ts = datetime.now(UTC).timestamp()
        headers_a = _signup_and_login(client, f"get_a_{ts}@example.com")
        headers_b = _signup_and_login(client, f"get_b_{ts}@example.com")

        booking = _build_booking(client, headers_a, Decimal("500.00"))
        create_res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking["id"], "amount": 500.00, "simulate_status": "SUCCESS"},
            headers=headers_a,
        )
        payment_id = create_res.json()["id"]

        get_res = client.get(f"/api/v1/payments/{payment_id}", headers=headers_b)
        assert get_res.status_code == 403

    def test_get_payment_requires_auth(self, client: TestClient):
        """Unauthenticated request → 401/403."""
        res = client.get("/api/v1/payments/1")
        assert res.status_code in (401, 403)


class TestInputValidation:
    """Schema-level input validation."""

    def test_pending_simulate_status_rejected(self, client: TestClient):
        """PENDING is not a valid simulate_status value."""
        headers = _signup_and_login(client)

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": 1, "amount": 100.00, "simulate_status": "PENDING"},
            headers=headers,
        )
        assert res.status_code == 422

    def test_invalid_simulate_status_rejected(self, client: TestClient):
        """Arbitrary strings are not accepted as simulate_status."""
        headers = _signup_and_login(client)

        res = client.post(
            "/api/v1/payments",
            json={"booking_id": 1, "amount": 100.00, "simulate_status": "PROCESSING"},
            headers=headers,
        )
        assert res.status_code == 422

    def test_payment_requires_authentication(self, client: TestClient):
        """POST /payments without a token → 401/403."""
        res = client.post(
            "/api/v1/payments",
            json={"booking_id": 1, "amount": 100.00, "simulate_status": "SUCCESS"},
        )
        assert res.status_code in (401, 403)
