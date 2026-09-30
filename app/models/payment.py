"""Payment ORM model.

Represents a payment attempt for a booking.  Multiple payment attempts may
exist for the same booking (e.g. first attempt failed; user retried).

The ``idempotency_key`` column is provided by the client to prevent duplicate
payment processing — the unique constraint on it enforces this at the database
level.

Relationships
-------------
- booking : many-to-one  →  Booking
- webhook_events : one-to-many  →  PaymentWebhookEvent
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.enums import PaymentStatus

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.webhook_event import PaymentWebhookEvent



class Payment(Base):
    """A payment attempt for a booking."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    # Externally visible reference (e.g. "PAY-20260930-XXXX")
    payment_reference: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    booking_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bookings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Must match booking.amount at the time of payment initiation
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status", native_enum=False),
        default=PaymentStatus.PENDING,
        index=True,
        nullable=False,
    )
    # Payment gateway identifier (e.g. "mock_gateway", "stripe", "razorpay")
    provider: Mapped[str] = mapped_column(
        String(50), default="mock_gateway", nullable=False
    )
    # Transaction ID assigned by the payment gateway on success/failure
    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    # Client-supplied deduplication key — unique where non-null
    idempotency_key: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    booking: Mapped["Booking"] = relationship("Booking", back_populates="payments")
    webhook_events: Mapped[list["PaymentWebhookEvent"]] = relationship(
        "PaymentWebhookEvent", back_populates="payment", cascade="all, delete-orphan"
    )

