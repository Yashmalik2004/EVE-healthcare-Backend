"""Payment data access layer.

Handles all persistence operations for Payment records, including idempotency
lookups and successful-payment detection used to prevent duplicate charges.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import PaymentStatus
from app.models.payment import Payment


class PaymentRepository:
    """Repository handling database queries and persistence for payments."""

    @staticmethod
    def get_by_id(db: Session, payment_id: int) -> Payment | None:
        """Fetch payment by primary key with the booking relation eagerly loaded."""
        return db.scalar(
            select(Payment)
            .where(Payment.id == payment_id)
            .options(selectinload(Payment.booking))
        )

    @staticmethod
    def get_by_idempotency_key(db: Session, idempotency_key: str) -> Payment | None:
        """Return an existing payment that was created with the given idempotency key.

        The database has a unique constraint on ``idempotency_key``, but we also
        query here to provide a fast early-return path before any validation runs.
        """
        return db.scalar(
            select(Payment)
            .where(Payment.idempotency_key == idempotency_key)
        )

    @staticmethod
    def get_successful_payment_for_booking(db: Session, booking_id: int) -> Payment | None:
        """Return a SUCCESS payment for a given booking, if one exists.

        Used to block duplicate successful payments on the same booking even
        when no idempotency key is provided.
        """
        return db.scalar(
            select(Payment).where(
                Payment.booking_id == booking_id,
                Payment.status == PaymentStatus.SUCCESS,
            )
        )

    @staticmethod
    def create(
        db: Session,
        *,
        booking_id: int,
        amount: Decimal,
        payment_reference: str,
        status: PaymentStatus,
        provider: str,
        provider_transaction_id: str | None,
        idempotency_key: str | None,
    ) -> Payment:
        """Persist a new Payment row and flush to obtain the primary key.

        The caller is responsible for calling ``db.commit()`` after this to
        atomically commit the payment and any associated booking-status change.
        """
        payment = Payment(
            booking_id=booking_id,
            amount=amount,
            payment_reference=payment_reference,
            status=status,
            provider=provider,
            provider_transaction_id=provider_transaction_id,
            idempotency_key=idempotency_key,
        )
        db.add(payment)
        db.flush()
        db.refresh(payment)
        return payment
