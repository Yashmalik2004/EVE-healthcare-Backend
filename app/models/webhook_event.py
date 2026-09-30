"""PaymentWebhookEvent ORM model.

Records inbound webhook notifications from the payment gateway.  The ``event_id``
unique constraint ensures that replayed or duplicated webhook deliveries are
detected and ignored (idempotent processing).

The ``payload`` column stores the raw JSON body of the webhook notification,
allowing full auditability and replay capability.

Relationships
-------------
- payment : many-to-one  →  Payment
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PaymentWebhookEvent(Base):
    """An inbound webhook event from the payment provider."""

    __tablename__ = "payment_webhook_events"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    # Unique event ID assigned by the payment gateway — used for idempotency
    event_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # payment_reference string linking the event to a payment record
    payment_reference: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    # FK to the Payment row (resolved after matching payment_reference)
    payment_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Raw JSON payload for full auditability and replay capability
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    # Timestamp set when the webhook has been fully processed
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    payment: Mapped["Payment | None"] = relationship(  # noqa: F821
        "Payment", back_populates="webhook_events"
    )
