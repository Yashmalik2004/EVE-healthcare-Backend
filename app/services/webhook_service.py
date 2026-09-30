"""Webhook processing service — payment gateway callback handler.

Architecture decisions
----------------------
* No authentication is required because this endpoint simulates an external
  payment provider callback that cannot provide a user JWT.  The event_id
  uniqueness constraint is the security/integrity boundary.

Idempotency and concurrency safety
-----------------------------------
Two-layer defence:

    Layer 1 — Application-level fast path:
        Query for event_id before doing any work.  If found, return
        ALREADY_PROCESSED immediately with no database writes.

    Layer 2 — Database UNIQUE(event_id) constraint:
        If two identical events race past Layer 1 simultaneously, only ONE
        INSERT will succeed.  The loser receives an IntegrityError.  We catch
        it, rollback the transaction, and re-query for the winning record to
        return a consistent ALREADY_PROCESSED response.

Payment lookup
--------------
    The webhook payload carries a ``payment_id`` field that is the
    PAY-YYYYMMDD-XXXXXXXX reference string (or a numeric ID as a string for
    legacy callers).  We resolve by reference first; if that fails and the
    string is all-digits we attempt a numeric ID lookup.

State transition rules
----------------------
    +-------------------------+------------+-------------------+
    | Booking current status  | WH status  | Booking new state |
    +-------------------------+------------+-------------------+
    | PENDING                 | SUCCESS    | CONFIRMED         |
    | PENDING                 | FAILED     | FAILED            |
    | CONFIRMED               | FAILED     | CANCELLED         |
    | CANCELLED               | any        | CANCELLED (kept)  |
    | FAILED                  | any        | FAILED (kept)     |
    +-------------------------+------------+-------------------+

    Terminal states (FAILED, CANCELLED) are never reversed.
    A CONFIRMED booking that receives a FAILED webhook is cancelled
    (edge case: gateway reports failure after a race-condition confirmation).

Atomicity
---------
    payment.status update
    + booking.status transition (via central state machine)
    + webhook_event INSERT
    are all within the same transaction and committed with a single db.commit().
"""

import json
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.core.logging import logger
from app.models.enums import BookingStatus, PaymentStatus
from app.repositories.payment_repository import PaymentRepository
from app.repositories.webhook_repository import WebhookRepository
from app.schemas.webhook import WebhookEventCreate, WebhookEventResponse
from app.services.booking_service import booking_service


class WebhookService:
    """Orchestrates inbound payment webhook processing with strict idempotency."""

    def __init__(
        self,
        webhook_repo: type[WebhookRepository] = WebhookRepository,
        payment_repo: type[PaymentRepository] = PaymentRepository,
    ):
        self.webhook_repo = webhook_repo
        self.payment_repo = payment_repo

    # ── Public API ────────────────────────────────────────────────────────────

    def process_webhook(
        self, db: Session, event_in: WebhookEventCreate
    ) -> WebhookEventResponse:
        """Process a payment gateway webhook notification.

        Steps
        -----
        1.  Fast-path idempotency check — return ALREADY_PROCESSED if seen.
        2.  Resolve the payment by reference or numeric ID.
        3.  Update payment status.
        4.  Apply booking state transition (respects terminal states).
        5.  Insert webhook event record (flush only).
        6.  Commit atomically.
        7.  On IntegrityError (concurrent duplicate) — rollback, re-query, return
            ALREADY_PROCESSED.
        """
        logger.info(
            f"Webhook received: event_id={event_in.event_id!r}, "
            f"event_type={event_in.event_type!r}, "
            f"payment_reference={event_in.payment_reference!r}, "
            f"status={event_in.status}"
        )

        # ── Step 1: Fast-path idempotency check ───────────────────────────────
        existing_event = self.webhook_repo.get_by_event_id(db, event_in.event_id)
        if existing_event:
            logger.info(
                f"Idempotent webhook: event_id={event_in.event_id!r} "
                f"was already processed at {existing_event.processed_at}"
            )
            return self._already_processed_response(event_in.event_id, existing_event.processed_at)

        # ── Step 2: Resolve payment ───────────────────────────────────────────
        payment = self.payment_repo.get_by_reference(db, event_in.payment_reference)

        # Fallback: legacy callers may send a numeric ID as a string
        if payment is None and event_in.payment_reference.isdigit():
            payment = self.payment_repo.get_by_id(db, int(event_in.payment_reference))

        if payment is None:
            logger.error(
                f"Webhook error: payment reference {event_in.payment_reference!r} not found"
            )
            raise NotFoundException("Payment", event_in.payment_reference)

        booking = payment.booking
        new_payment_status = event_in.status

        # ── Step 3: Update payment status ─────────────────────────────────────
        payment.status = new_payment_status
        db.flush()  # make the update visible within the transaction

        # ── Step 4: Booking state transition ──────────────────────────────────
        self._apply_booking_transition(db, booking, new_payment_status)

        # ── Step 5: Insert webhook event (flush only) ─────────────────────────
        now_dt = datetime.now(UTC)
        payload_str = json.dumps(event_in.model_dump(mode="json"))

        try:
            event_record = self.webhook_repo.create_event(
                db=db,
                event_id=event_in.event_id,
                event_type=event_in.event_type,
                payment_reference=event_in.payment_reference,
                payment_db_id=payment.id,
                payload=payload_str,
                processed_at=now_dt,
            )
            # ── Step 6: Atomic commit ──────────────────────────────────────────
            db.commit()
            logger.info(
                f"Webhook processed: event_id={event_in.event_id!r}, "
                f"payment_status={payment.status}, booking_status={booking.status}"
            )

        except IntegrityError:
            # ── Step 7: Concurrent duplicate — rollback and re-query ──────────
            db.rollback()
            logger.warning(
                f"Concurrent duplicate webhook detected for "
                f"event_id={event_in.event_id!r}; returning ALREADY_PROCESSED"
            )
            existing_event = self.webhook_repo.get_by_event_id(db, event_in.event_id)
            processed_ts = existing_event.processed_at if existing_event else now_dt
            return self._already_processed_response(event_in.event_id, processed_ts)

        return WebhookEventResponse(
            success=True,
            event_id=event_record.event_id,
            message="Webhook processed successfully.",
            status=new_payment_status.value,
            processed_at=event_record.processed_at,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _already_processed_response(
        event_id: str, processed_at: datetime | None
    ) -> WebhookEventResponse:
        """Build a consistent ALREADY_PROCESSED response."""
        return WebhookEventResponse(
            success=True,
            event_id=event_id,
            message="Webhook event already processed.",
            status="ALREADY_PROCESSED",
            processed_at=processed_at,
        )

    @staticmethod
    def _apply_booking_transition(
        db: Session,
        booking,
        new_payment_status: PaymentStatus,
    ) -> None:
        """Apply the appropriate booking state transition based on payment outcome.

        Rules
        -----
        CANCELLED:
            Never revived regardless of payment outcome.  Log a warning and
            leave the booking in CANCELLED state.

        FAILED (terminal):
            Already terminal — no further transition.

        PENDING:
            SUCCESS → CONFIRMED
            FAILED  → FAILED

        CONFIRMED:
            FAILED → CANCELLED  (late failure after optimistic confirmation)
            SUCCESS → no-op     (already confirmed)
        """
        current = booking.status

        if current == BookingStatus.CANCELLED:
            logger.warning(
                f"Webhook: booking ref={booking.booking_reference} is CANCELLED; "
                "retaining CANCELLED state regardless of payment outcome."
            )
            return

        if current == BookingStatus.FAILED:
            logger.info(
                f"Webhook: booking ref={booking.booking_reference} is already FAILED (terminal); "
                "no further transition applied."
            )
            return

        if current == BookingStatus.PENDING:
            if new_payment_status == PaymentStatus.SUCCESS:
                booking_service.transition_status(db, booking, BookingStatus.CONFIRMED)
            else:
                booking_service.transition_status(db, booking, BookingStatus.FAILED)
            return

        if current == BookingStatus.CONFIRMED:
            if new_payment_status == PaymentStatus.FAILED:
                logger.warning(
                    f"Webhook: CONFIRMED booking {booking.booking_reference} "
                    "received FAILED payment — transitioning to CANCELLED."
                )
                booking_service.transition_status(db, booking, BookingStatus.CANCELLED)
            # SUCCESS on an already CONFIRMED booking is a no-op
            return


webhook_service = WebhookService()
