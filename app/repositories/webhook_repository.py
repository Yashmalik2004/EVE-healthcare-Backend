"""Webhook event data access layer.

Handles all persistence operations for PaymentWebhookEvent records.

The ``create_event`` method only flushes — it does NOT commit.  Committing is
left to the service layer so that the webhook event insertion, payment status
update, and booking state transition are all committed atomically in one
``db.commit()`` call.

The database UNIQUE constraint on ``event_id`` is the final concurrency guard:
if two identical events race past the application-level idempotency check, only
one INSERT will succeed; the other will receive an ``IntegrityError`` which the
service layer catches and handles gracefully.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.webhook_event import PaymentWebhookEvent


class WebhookRepository:
    """Repository for inbound webhook event storage and lookup."""

    @staticmethod
    def get_by_event_id(db: Session, event_id: str) -> PaymentWebhookEvent | None:
        """Return the persisted webhook event with the given ``event_id``, or ``None``.

        Used for both the fast-path idempotency check (before any processing)
        and the post-rollback re-query (after a concurrent IntegrityError).
        """
        return db.scalar(
            select(PaymentWebhookEvent).where(PaymentWebhookEvent.event_id == event_id)
        )

    @staticmethod
    def create_event(
        db: Session,
        *,
        event_id: str,
        event_type: str,
        payment_reference: str,
        payment_db_id: int | None,
        payload: str,
        processed_at: datetime | None = None,
    ) -> PaymentWebhookEvent:
        """Insert a new webhook event row and flush (does NOT commit).

        Parameters
        ----------
        event_id:
            Unique identifier assigned by the payment gateway.
        event_type:
            Descriptor string (e.g. ``"payment.updated"``).
        payment_reference:
            The human-readable payment reference string (PAY-...).
        payment_db_id:
            The resolved Payment primary key, used for the FK relationship.
        payload:
            Raw JSON body of the webhook notification for full auditability.
        processed_at:
            Timestamp of processing; defaults to ``datetime.now(UTC)``.
        """
        event = PaymentWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            payment_reference=payment_reference,
            payment_id=payment_db_id,
            payload=payload,
            processed_at=processed_at or datetime.now(UTC),
        )
        db.add(event)
        db.flush()
        db.refresh(event)
        return event
