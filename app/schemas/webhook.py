"""Webhook event Pydantic schemas — inbound event and response models.

Design notes
------------
* ``status`` accepts only SUCCESS or FAILED — PENDING is not a valid webhook
  outcome (the payment gateway never sends a "still pending" callback).
* ``payment_reference`` is a string field accepting either the human-readable
  PAY-YYYYMMDD-XXXXXXXX reference or the numeric payment ID (as a string).
* ``event_type`` has a sensible default but is validated as a non-empty string.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import PaymentStatus


class WebhookEventCreate(BaseModel):
    """Schema for an inbound webhook notification from the payment provider.

    All fields are required. The ``status`` field is constrained to SUCCESS or
    FAILED — PENDING is not an acceptable gateway-reported outcome.
    """

    event_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique event ID assigned by the payment gateway (used for idempotency)",
    )
    event_type: str = Field(
        default="payment.updated",
        min_length=1,
        max_length=100,
        description="Type of the webhook event (e.g. 'payment.updated', 'payment.completed')",
    )
    payment_reference: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Payment reference (PAY-YYYYMMDD-XXXXXXXX) or numeric payment ID",
        alias="payment_id",
    )
    status: PaymentStatus = Field(
        ...,
        description="Payment outcome reported by the gateway: SUCCESS or FAILED",
    )

    @field_validator("status")
    @classmethod
    def validate_outcome_status(cls, v: PaymentStatus) -> PaymentStatus:
        """Reject PENDING — the gateway must report a definitive outcome."""
        if v == PaymentStatus.PENDING:
            raise ValueError(
                "Webhook status must be 'SUCCESS' or 'FAILED'; "
                "'PENDING' is not a valid gateway-reported outcome."
            )
        return v

    model_config = ConfigDict(populate_by_name=True)


class WebhookEventResponse(BaseModel):
    """Structured response returned after processing a webhook event.

    ``status`` is a string (not the PaymentStatus enum) so that the special
    sentinel value ``ALREADY_PROCESSED`` can be returned for duplicate events
    without expanding the enum.
    """

    success: bool = True
    event_id: str
    message: str
    status: str  # "SUCCESS", "FAILED", or "ALREADY_PROCESSED"
    processed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
