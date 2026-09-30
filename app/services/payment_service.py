"""Simulated payment processing service.

Architecture decisions
----------------------
* The client supplies ``simulate_status`` (SUCCESS | FAILED); there is no real
  payment gateway.
* Booking.amount is the authoritative amount — client-supplied ``amount`` must
  equal it exactly (amount verification at step 4 below).
* All booking state transitions are delegated to ``BookingService.transition_status``
  so the state machine remains centralised in one place.
* The payment record and booking status change are committed in a single
  ``db.commit()`` call for atomicity.
* Idempotency key deduplication happens before any validation so repeated
  requests with the same key are short-circuited safely.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.core.logging import logger
from app.models.enums import BookingStatus, PaymentStatus, UserRole
from app.models.payment import Payment
from app.models.user import User
from app.repositories.booking_repository import BookingRepository
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentCreate
from app.services.booking_service import booking_service


class PaymentService:
    """Orchestrates simulated payment creation, validation, and booking state transitions."""

    def __init__(
        self,
        payment_repo: type[PaymentRepository] = PaymentRepository,
        booking_repo: type[BookingRepository] = BookingRepository,
    ):
        self.payment_repo = payment_repo
        self.booking_repo = booking_repo

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_payment_reference() -> str:
        """Return a human-readable, unique payment reference (e.g. PAY-20260930-AB12CD34)."""
        date_prefix = datetime.now(UTC).strftime("%Y%m%d")
        unique_suffix = uuid.uuid4().hex[:8].upper()
        return f"PAY-{date_prefix}-{unique_suffix}"

    @staticmethod
    def _generate_provider_transaction_id() -> str:
        """Return a mock gateway transaction ID."""
        return f"tx_{uuid.uuid4().hex[:12]}"

    # ── Commands ──────────────────────────────────────────────────────────────

    def process_payment(
        self,
        db: Session,
        user: User,
        payment_in: PaymentCreate,
        idempotency_key: str | None = None,
    ) -> Payment:
        """Process a simulated payment following the 14-step validation flow.

        Steps
        -----
        1.  Idempotency — if the key was seen before, return the existing payment.
        2.  Fetch booking; raise 404 if absent.
        3.  Ownership check — raise 403 if user does not own the booking.
        4.  Booking-status guards — raise 409 for CONFIRMED / CANCELLED / FAILED.
        5.  Duplicate-success guard — raise 409 if a SUCCESS payment already exists.
        6.  Amount verification — raise 422 if amount != booking.amount.
        7.  Create payment record.
        8.  Transition booking status (SUCCESS→CONFIRMED, FAILED→FAILED).
        9.  Commit atomically and return the refreshed payment.
        """
        logger.info(
            f"Processing payment: booking_id={payment_in.booking_id}, "
            f"amount={payment_in.amount}, simulate_status={payment_in.simulate_status}, "
            f"idempotency_key={idempotency_key!r}"
        )

        # Step 1 — Idempotency key early return
        if idempotency_key:
            existing = self.payment_repo.get_by_idempotency_key(db, idempotency_key)
            if existing:
                logger.info(
                    f"Idempotent return for key={idempotency_key!r}, "
                    f"payment_ref={existing.payment_reference}"
                )
                return existing

        # Step 2 — Fetch booking
        booking = self.booking_repo.get_by_id(db, payment_in.booking_id)
        if not booking:
            raise NotFoundException("Booking", payment_in.booking_id)

        # Step 3 — Ownership
        if user.role != UserRole.ADMIN and booking.user_id != user.id:
            logger.warning(
                f"Unauthorized payment attempt: user_id={user.id} on booking_id={booking.id}"
            )
            raise ForbiddenException("You are not authorized to pay for this booking.")

        # Steps 4a–4c — Booking status guards
        if booking.status == BookingStatus.CONFIRMED:
            raise ConflictException(
                "BOOKING_ALREADY_CONFIRMED",
                "This booking is already paid and confirmed.",
            )
        if booking.status == BookingStatus.CANCELLED:
            raise ConflictException(
                "BOOKING_ALREADY_CANCELLED",
                "Cannot make payment for a cancelled booking.",
            )
        if booking.status == BookingStatus.FAILED:
            raise ConflictException(
                "BOOKING_FAILED",
                "Cannot make payment for a booking that is already in FAILED status.",
            )

        # Step 5 — Duplicate successful payment guard
        successful_payment = self.payment_repo.get_successful_payment_for_booking(
            db, booking.id
        )
        if successful_payment:
            raise ConflictException(
                "PAYMENT_ALREADY_COMPLETED",
                "A successful payment already exists for this booking.",
            )

        # Step 6 — Amount verification (Booking.amount is authoritative)
        if payment_in.amount != booking.amount:
            logger.warning(
                f"Amount mismatch: received {payment_in.amount}, "
                f"expected {booking.amount} for booking_id={booking.id}"
            )
            raise ValidationException(
                "PAYMENT_AMOUNT_MISMATCH",
                f"Provided amount '{payment_in.amount}' does not match "
                f"the booking amount '{booking.amount}'.",
            )

        # Step 7 — Create payment record (flushed, not yet committed)
        payment_ref = self._generate_payment_reference()
        provider_tx_id = self._generate_provider_transaction_id()
        simulated_status = payment_in.simulate_status

        payment = self.payment_repo.create(
            db=db,
            booking_id=booking.id,
            amount=payment_in.amount,
            payment_reference=payment_ref,
            status=simulated_status,
            provider="mock_gateway",
            provider_transaction_id=provider_tx_id,
            idempotency_key=idempotency_key,
        )

        # Step 8 — Transition booking state (delegated to central state machine)
        if simulated_status == PaymentStatus.SUCCESS:
            booking_service.transition_status(db, booking, BookingStatus.CONFIRMED)
        else:
            booking_service.transition_status(db, booking, BookingStatus.FAILED)

        # Step 9 — Atomic commit
        db.commit()
        db.refresh(payment)

        logger.info(
            f"Payment processed: ref={payment.payment_reference}, "
            f"status={payment.status}, booking_status={booking.status}"
        )
        return payment

    def get_payment(self, db: Session, user: User, payment_id: int) -> Payment:
        """Retrieve a payment by ID with an ownership check.

        Raises
        ------
        NotFoundException  — payment does not exist.
        ForbiddenException — authenticated user does not own the associated booking.
        """
        payment = self.payment_repo.get_by_id(db, payment_id)
        if not payment:
            raise NotFoundException("Payment", payment_id)

        if user.role != UserRole.ADMIN and payment.booking.user_id != user.id:
            logger.warning(
                f"Unauthorized payment access: user_id={user.id} on payment_id={payment_id}"
            )
            raise ForbiddenException("You are not authorized to view this payment.")

        return payment


payment_service = PaymentService()
