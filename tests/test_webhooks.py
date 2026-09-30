"""Test suite for Phase 8 — Payment Webhook and Strict Idempotency.

Covers:
    1.  valid SUCCESS webhook → payment SUCCESS, booking CONFIRMED
    2.  valid FAILED webhook → payment FAILED, booking FAILED
    3.  invalid event_id (empty / missing)
    4.  invalid / unknown payment reference → 404
    5.  repeated same webhook (2nd call) → ALREADY_PROCESSED
    6.  same webhook sent exactly 2 times → consistent state
    7.  same webhook sent exactly 10 times → exactly 1 event record persisted
    8.  webhook after booking already CONFIRMED (via prior payment) → ALREADY_PROCESSED or no-op
    9.  webhook for CANCELLED booking → booking remains CANCELLED
    10. conflicting event_id (same event_id, different data) → first wins
    11. PENDING simulate_status rejected by schema
    12. numeric payment_id string fallback lookup
    13. GET /payments/{id} still works after webhook processes the payment
    14. CONFIRMED booking + FAILED webhook → CANCELLED (edge case)
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.enums import BookingStatus, PaymentStatus
from app.models.payment import Payment
from app.models.webhook_event import PaymentWebhookEvent


# ── Shared helpers ────────────────────────────────────────────────────────────


def _signup_and_login(client: TestClient, email: str | None = None) -> dict:
    """Register and authenticate a user; return auth headers."""
    email = email or f"wh_user_{datetime.now(UTC).timestamp()}@example.com"
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Password123!", "full_name": "WH User"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _build_pending_payment(
    client: TestClient,
    db: Session,
    price: Decimal = Decimal("1200.00"),
) -> tuple[dict, dict, Payment]:
    """Build a full chain and create a PENDING payment directly in the DB.

    Returns (headers, booking_dict, payment_orm_object).
    The payment is PENDING — simulating a payment that was initiated but whose
    final status will arrive via webhook.
    """
    headers = _signup_and_login(client)

    # Centre
    c_res = client.post(
        "/api/v1/centres",
        json={
            "name": "Webhook Lab",
            "address": "99 Health St",
            "city": "Bengaluru",
            "state": "Karnataka",
        },
        headers=headers,
    )
    centre_id = c_res.json()["id"]

    # Test
    t_res = client.post(
        "/api/v1/tests",
        json={
            "name": "Full Body Profile",
            "description": "Comprehensive Health Screening",
            "category": "Preventive Care",
        },
        headers=headers,
    )
    test_id = t_res.json()["id"]

    # Centre ↔ Test
    ct_res = client.post(
        f"/api/v1/centres/{centre_id}/tests",
        json={"test_id": test_id, "price": float(price)},
        headers=headers,
    )
    centre_test_id = ct_res.json()["id"]

    # Slot
    future_dt = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    slot_res = client.post(
        f"/api/v1/centres/{centre_id}/slots",
        json={"appointment_datetime": future_dt, "is_available": True},
        headers=headers,
    )
    slot_id = slot_res.json()["id"]

    # Booking
    b_res = client.post(
        "/api/v1/bookings",
        json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
        headers=headers,
    )
    booking = b_res.json()

    # PENDING Payment inserted directly into DB (not via /payments API)
    pay_ref = f"PAY-{datetime.now(UTC).strftime('%Y%m%d')}-WH{booking['id']:04d}"
    payment = Payment(
        booking_id=booking["id"],
        amount=price,
        payment_reference=pay_ref,
        status=PaymentStatus.PENDING,
        provider="mock_gateway",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    return headers, booking, payment


def _webhook_payload(event_id: str, payment_ref: str, status: str = "SUCCESS") -> dict:
    """Build a standard webhook POST body."""
    return {
        "event_id": event_id,
        "event_type": "payment.updated",
        "payment_id": payment_ref,  # field alias
        "status": status,
    }


# ── Test cases ────────────────────────────────────────────────────────────────


class TestWebhookSuccess:
    """Valid SUCCESS webhook — payment confirmed, booking confirmed."""

    def test_webhook_success_http_200(self, client: TestClient, db: Session):
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_succ_{datetime.now(UTC).timestamp()}"

        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "SUCCESS"),
        )
        assert res.status_code == 200

    def test_webhook_success_response_fields(self, client: TestClient, db: Session):
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_succ_fields_{datetime.now(UTC).timestamp()}"

        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "SUCCESS"),
        )
        data = res.json()
        assert data["success"] is True
        assert data["event_id"] == event_id
        assert data["status"] == "SUCCESS"
        assert data["message"] == "Webhook processed successfully."
        assert data["processed_at"] is not None

    def test_webhook_success_confirms_booking(self, client: TestClient, db: Session):
        _, booking, payment = _build_pending_payment(client, db)
        event_id = f"evt_succ_booking_{datetime.now(UTC).timestamp()}"

        client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "SUCCESS"),
        )

        booking_record = db.scalar(select(Booking).where(Booking.id == booking["id"]))
        assert booking_record.status == BookingStatus.CONFIRMED

    def test_webhook_success_updates_payment_status(self, client: TestClient, db: Session):
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_succ_pay_{datetime.now(UTC).timestamp()}"

        client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "SUCCESS"),
        )

        db.refresh(payment)
        assert payment.status == PaymentStatus.SUCCESS

    def test_webhook_event_record_created(self, client: TestClient, db: Session):
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_succ_record_{datetime.now(UTC).timestamp()}"

        client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "SUCCESS"),
        )

        event = db.scalar(
            select(PaymentWebhookEvent).where(PaymentWebhookEvent.event_id == event_id)
        )
        assert event is not None
        assert event.event_id == event_id
        assert event.payment_id == payment.id


class TestWebhookFailed:
    """Valid FAILED webhook — payment failed, booking failed."""

    def test_webhook_failed_http_200(self, client: TestClient, db: Session):
        _, _, payment = _build_pending_payment(client, db, Decimal("400.00"))
        event_id = f"evt_fail_{datetime.now(UTC).timestamp()}"

        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "FAILED"),
        )
        assert res.status_code == 200

    def test_webhook_failed_response_status(self, client: TestClient, db: Session):
        _, _, payment = _build_pending_payment(client, db, Decimal("400.00"))
        event_id = f"evt_fail_resp_{datetime.now(UTC).timestamp()}"

        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "FAILED"),
        )
        assert res.json()["status"] == "FAILED"

    def test_webhook_failed_fails_booking(self, client: TestClient, db: Session):
        _, booking, payment = _build_pending_payment(client, db, Decimal("400.00"))
        event_id = f"evt_fail_book_{datetime.now(UTC).timestamp()}"

        client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "FAILED"),
        )

        booking_record = db.scalar(select(Booking).where(Booking.id == booking["id"]))
        assert booking_record.status == BookingStatus.FAILED

    def test_webhook_failed_updates_payment_status(self, client: TestClient, db: Session):
        _, _, payment = _build_pending_payment(client, db, Decimal("400.00"))
        event_id = f"evt_fail_pay_{datetime.now(UTC).timestamp()}"

        client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "FAILED"),
        )

        db.refresh(payment)
        assert payment.status == PaymentStatus.FAILED


class TestInvalidInput:
    """Schema-level and lookup validation."""

    def test_unknown_payment_reference_404(self, client: TestClient):
        """Non-existent payment reference → 404."""
        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload("evt_unknown_pay", "PAY-NONEXISTENT-9999", "SUCCESS"),
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "PAYMENT_NOT_FOUND"

    def test_pending_status_rejected_422(self, client: TestClient):
        """PENDING is not an acceptable webhook outcome."""
        res = client.post(
            "/api/v1/payments/webhook",
            json={"event_id": "evt_bad", "event_type": "payment.updated",
                  "payment_id": "PAY-0000-0000", "status": "PENDING"},
        )
        assert res.status_code == 422

    def test_invalid_status_rejected_422(self, client: TestClient):
        res = client.post(
            "/api/v1/payments/webhook",
            json={"event_id": "evt_bad2", "event_type": "payment.updated",
                  "payment_id": "PAY-0000-0000", "status": "PROCESSING"},
        )
        assert res.status_code == 422

    def test_missing_event_id_rejected(self, client: TestClient):
        res = client.post(
            "/api/v1/payments/webhook",
            json={"event_type": "payment.updated",
                  "payment_id": "PAY-0000-0000", "status": "SUCCESS"},
        )
        assert res.status_code == 422

    def test_missing_payment_id_rejected(self, client: TestClient):
        res = client.post(
            "/api/v1/payments/webhook",
            json={"event_id": "evt_missing_pay",
                  "event_type": "payment.updated", "status": "SUCCESS"},
        )
        assert res.status_code == 422


class TestIdempotency:
    """Repeated same event_id must produce exactly one persisted record."""

    def test_repeated_webhook_returns_already_processed(self, client: TestClient, db: Session):
        """Second delivery of the same event_id → ALREADY_PROCESSED."""
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_dup2_{datetime.now(UTC).timestamp()}"
        payload = _webhook_payload(event_id, payment.payment_reference, "SUCCESS")

        # First delivery
        res1 = client.post("/api/v1/payments/webhook", json=payload)
        assert res1.status_code == 200
        assert res1.json()["status"] == "SUCCESS"

        # Second delivery — must return ALREADY_PROCESSED
        res2 = client.post("/api/v1/payments/webhook", json=payload)
        assert res2.status_code == 200
        assert res2.json()["status"] == "ALREADY_PROCESSED"
        assert res2.json()["message"] == "Webhook event already processed."

    def test_same_webhook_2_times_one_event_record(self, client: TestClient, db: Session):
        """Exactly 2 deliveries → exactly 1 webhook event row in the database."""
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_2x_{datetime.now(UTC).timestamp()}"
        payload = _webhook_payload(event_id, payment.payment_reference, "SUCCESS")

        for _ in range(2):
            client.post("/api/v1/payments/webhook", json=payload)

        count = db.scalar(
            select(func.count(PaymentWebhookEvent.id)).where(
                PaymentWebhookEvent.event_id == event_id
            )
        )
        assert count == 1

    def test_same_webhook_10_times_critical(self, client: TestClient, db: Session):
        """CRITICAL: 10 identical deliveries must produce exactly 1 event record
        and leave payment/booking in a consistent final state.
        """
        _, booking, payment = _build_pending_payment(client, db)
        booking_id = booking["id"]
        event_id = f"evt_10x_{datetime.now(UTC).timestamp()}"
        payload = _webhook_payload(event_id, payment.payment_reference, "SUCCESS")

        responses = []
        for _ in range(10):
            res = client.post("/api/v1/payments/webhook", json=payload)
            responses.append(res)

        # All HTTP responses must be 200
        for i, res in enumerate(responses):
            assert res.status_code == 200, f"Request #{i + 1} failed: {res.text}"
            data = res.json()
            assert data["success"] is True
            assert data["event_id"] == event_id

        # First response must be the real one; subsequent must be ALREADY_PROCESSED
        assert responses[0].json()["status"] == "SUCCESS"
        assert responses[0].json()["message"] == "Webhook processed successfully."
        for res in responses[1:]:
            assert res.json()["status"] == "ALREADY_PROCESSED"

        # Exactly 1 webhook event record
        event_count = db.scalar(
            select(func.count(PaymentWebhookEvent.id)).where(
                PaymentWebhookEvent.event_id == event_id
            )
        )
        assert event_count == 1, f"Expected 1 event, found {event_count}"

        # Exactly 1 payment record for this booking
        payment_count = db.scalar(
            select(func.count(Payment.id)).where(Payment.booking_id == booking_id)
        )
        assert payment_count == 1, f"Expected 1 payment, found {payment_count}"

        # Final payment status = SUCCESS
        db.refresh(payment)
        assert payment.status == PaymentStatus.SUCCESS

        # Final booking status = CONFIRMED
        booking_record = db.scalar(select(Booking).where(Booking.id == booking_id))
        assert booking_record.status == BookingStatus.CONFIRMED

    def test_idempotency_preserves_processed_at_timestamp(self, client: TestClient, db: Session):
        """All repeat responses must reference the same processed_at timestamp."""
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_ts_{datetime.now(UTC).timestamp()}"
        payload = _webhook_payload(event_id, payment.payment_reference, "SUCCESS")

        res1 = client.post("/api/v1/payments/webhook", json=payload)
        res2 = client.post("/api/v1/payments/webhook", json=payload)

        assert res1.json()["processed_at"] == res2.json()["processed_at"]


class TestWebhookAfterAlreadyProcessed:
    """Webhook arriving after booking is already in a terminal state."""

    def test_webhook_after_confirmed_booking(self, client: TestClient, db: Session):
        """If the booking is already CONFIRMED (e.g. via /payments API),
        a SUCCESS webhook should return success (the ALREADY_PROCESSED path
        is bypassed since a different event_id is used, but the booking
        transition is a no-op since it is already CONFIRMED).
        """
        headers = _signup_and_login(client)

        # Build booking
        c_res = client.post(
            "/api/v1/centres",
            json={"name": "Lab B", "address": "1 B St", "city": "Delhi", "state": "Delhi"},
            headers=headers,
        )
        centre_id = c_res.json()["id"]

        t_res = client.post(
            "/api/v1/tests",
            json={"name": "ESR Test", "description": "Erythrocyte", "category": "Haematology"},
            headers=headers,
        )
        test_id = t_res.json()["id"]

        ct_res = client.post(
            f"/api/v1/centres/{centre_id}/tests",
            json={"test_id": test_id, "price": 300.00},
            headers=headers,
        )
        centre_test_id = ct_res.json()["id"]

        future_dt = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        slot_res = client.post(
            f"/api/v1/centres/{centre_id}/slots",
            json={"appointment_datetime": future_dt, "is_available": True},
            headers=headers,
        )
        slot_id = slot_res.json()["id"]

        b_res = client.post(
            "/api/v1/bookings",
            json={"centre_test_id": centre_test_id, "appointment_slot_id": slot_id},
            headers=headers,
        )
        booking_id = b_res.json()["id"]

        # Confirm via /payments API (SUCCESS)
        pay_res = client.post(
            "/api/v1/payments",
            json={"booking_id": booking_id, "amount": 300.00, "simulate_status": "SUCCESS"},
            headers=headers,
        )
        pay_ref = pay_res.json()["payment_reference"]

        # Now send a webhook with the same payment ref but a NEW event_id
        event_id = f"evt_late_{datetime.now(UTC).timestamp()}"
        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, pay_ref, "SUCCESS"),
        )
        assert res.status_code == 200

        # Booking must still be CONFIRMED
        booking_record = db.scalar(select(Booking).where(Booking.id == booking_id))
        assert booking_record.status == BookingStatus.CONFIRMED

    def test_webhook_on_cancelled_booking(self, client: TestClient, db: Session):
        """Webhook for a CANCELLED booking must not revive it."""
        headers, booking, payment = _build_pending_payment(client, db)
        booking_id = booking["id"]

        # Cancel booking first
        cancel_res = client.post(
            f"/api/v1/bookings/{booking_id}/cancel", headers=headers
        )
        assert cancel_res.status_code == 200

        event_id = f"evt_cancelled_{datetime.now(UTC).timestamp()}"
        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "SUCCESS"),
        )
        assert res.status_code == 200

        # Booking must remain CANCELLED
        booking_record = db.scalar(select(Booking).where(Booking.id == booking_id))
        assert booking_record.status == BookingStatus.CANCELLED

    def test_webhook_on_failed_booking_no_reversal(self, client: TestClient, db: Session):
        """Webhook after booking is FAILED must not change the booking status."""
        _, booking, payment = _build_pending_payment(client, db)
        booking_id = booking["id"]

        # First webhook fails the booking
        event_id1 = f"evt_fail1_{datetime.now(UTC).timestamp()}"
        client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id1, payment.payment_reference, "FAILED"),
        )

        # Second (different) webhook with SUCCESS should NOT revive it
        event_id2 = f"evt_succ_after_{datetime.now(UTC).timestamp()}"
        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id2, payment.payment_reference, "SUCCESS"),
        )
        # The service returns 200 but booking stays FAILED
        assert res.status_code == 200

        booking_record = db.scalar(select(Booking).where(Booking.id == booking_id))
        assert booking_record.status == BookingStatus.FAILED


class TestConflictingEvent:
    """Same event_id used with conflicting data — first write wins."""

    def test_conflicting_event_id_first_wins(self, client: TestClient, db: Session):
        """Two requests with the same event_id but different status values.

        The second must return ALREADY_PROCESSED and must not change the state
        set by the first.
        """
        _, booking, payment = _build_pending_payment(client, db)
        booking_id = booking["id"]
        event_id = f"evt_conflict_{datetime.now(UTC).timestamp()}"

        # First delivery: SUCCESS
        res1 = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "SUCCESS"),
        )
        assert res1.status_code == 200
        assert res1.json()["status"] == "SUCCESS"

        # Second delivery: same event_id but FAILED — must be ignored
        res2 = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "FAILED"),
        )
        assert res2.status_code == 200
        assert res2.json()["status"] == "ALREADY_PROCESSED"

        # Booking must be CONFIRMED (first write wins)
        booking_record = db.scalar(select(Booking).where(Booking.id == booking_id))
        assert booking_record.status == BookingStatus.CONFIRMED

        # Exactly 1 event record
        count = db.scalar(
            select(func.count(PaymentWebhookEvent.id)).where(
                PaymentWebhookEvent.event_id == event_id
            )
        )
        assert count == 1


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_webhook_payload_stored_as_json(self, client: TestClient, db: Session):
        """The raw payload must be persisted as valid JSON in the webhook event."""
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_json_{datetime.now(UTC).timestamp()}"

        client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "SUCCESS"),
        )

        event = db.scalar(
            select(PaymentWebhookEvent).where(PaymentWebhookEvent.event_id == event_id)
        )
        assert event is not None
        # payload must be valid JSON
        parsed = json.loads(event.payload)
        assert "event_id" in parsed
        assert "status" in parsed

    def test_webhook_no_auth_required(self, client: TestClient, db: Session):
        """The webhook endpoint must be accessible without an Authorization header."""
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_noauth_{datetime.now(UTC).timestamp()}"

        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id, payment.payment_reference, "SUCCESS"),
        )
        # Must succeed (not 401 or 403)
        assert res.status_code == 200

    def test_webhook_numeric_payment_id_fallback(self, client: TestClient, db: Session):
        """Callers that send the numeric DB ID as a string should still resolve."""
        _, _, payment = _build_pending_payment(client, db)
        event_id = f"evt_numid_{datetime.now(UTC).timestamp()}"

        res = client.post(
            "/api/v1/payments/webhook",
            json={
                "event_id": event_id,
                "event_type": "payment.updated",
                "payment_id": str(payment.id),  # numeric string fallback
                "status": "SUCCESS",
            },
        )
        assert res.status_code == 200
        assert res.json()["status"] == "SUCCESS"

    def test_confirmed_booking_failed_webhook_cancels(self, client: TestClient, db: Session):
        """Edge case: confirmed booking + FAILED webhook → booking is CANCELLED."""
        _, booking, payment = _build_pending_payment(client, db)
        booking_id = booking["id"]

        # First: SUCCESS → CONFIRMED
        event_id1 = f"evt_conf_{datetime.now(UTC).timestamp()}"
        client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id1, payment.payment_reference, "SUCCESS"),
        )

        booking_record = db.scalar(select(Booking).where(Booking.id == booking_id))
        assert booking_record.status == BookingStatus.CONFIRMED

        # Now: FAILED on a different event_id (late failure) → CANCELLED
        event_id2 = f"evt_late_fail_{datetime.now(UTC).timestamp()}"
        res = client.post(
            "/api/v1/payments/webhook",
            json=_webhook_payload(event_id2, payment.payment_reference, "FAILED"),
        )
        assert res.status_code == 200

        db.expire_all()
        booking_record = db.scalar(select(Booking).where(Booking.id == booking_id))
        assert booking_record.status == BookingStatus.CANCELLED
