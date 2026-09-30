"""Payment Pydantic schemas — request and response models."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import PaymentStatus


class PaymentCreate(BaseModel):
    """Schema for initiating a simulated payment.

    ``simulate_status`` must be either ``SUCCESS`` or ``FAILED``; ``PENDING``
    is intentionally excluded because the client cannot declare an indeterminate
    outcome — only the gateway (simulated here) can.
    """

    booking_id: int = Field(..., ge=1, description="ID of the booking to pay for")
    amount: Decimal = Field(
        ...,
        gt=0,
        decimal_places=2,
        description="Payment amount — must exactly match Booking.amount",
    )
    simulate_status: PaymentStatus = Field(
        ...,
        description="Simulated payment outcome: SUCCESS or FAILED",
    )

    @field_validator("simulate_status")
    @classmethod
    def validate_simulate_status(cls, v: PaymentStatus) -> PaymentStatus:
        """Disallow PENDING as a client-supplied simulated status."""
        if v == PaymentStatus.PENDING:
            raise ValueError(
                "simulate_status must be 'SUCCESS' or 'FAILED'; 'PENDING' is not a valid input."
            )
        return v


class PaymentResponse(BaseModel):
    """Schema for a payment record returned in API responses."""

    id: int
    payment_reference: str
    booking_id: int
    amount: Decimal
    status: PaymentStatus
    provider: str
    provider_transaction_id: str | None = None
    idempotency_key: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
