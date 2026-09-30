"""Webhook endpoint — payment gateway callback receiver.

POST /payments/webhook

No authentication is required.  This endpoint simulates an external payment
provider posting an event notification.  All security is handled by:
    - strict schema validation (event_id, payment_reference, status enum)
    - event_id uniqueness (database UNIQUE constraint)

The route is deliberately mounted on the ``/payments`` prefix rather than a
separate top-level ``/webhooks`` prefix so that it co-locates with the payment
domain and allows the router to be registered under ``payments.router`` in
main.py, avoiding an extra router import.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit_ip
from app.db.database import get_db
from app.schemas.webhook import WebhookEventCreate, WebhookEventResponse
from app.services.webhook_service import webhook_service

router = APIRouter(prefix="/payments/webhook", tags=["Payments"])


@router.post(
    "",
    response_model=WebhookEventResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_ip(requests=30, window=60, scope="payments:webhook"))],
    summary="Receive a payment gateway webhook",

    description=(
        "Handles inbound payment gateway webhook notifications. "
        "No authentication required — this represents an external provider callback. "
        "Idempotent: repeated delivery of the same ``event_id`` returns "
        "``ALREADY_PROCESSED`` without modifying any records."
    ),
)
def receive_webhook(
    event_in: WebhookEventCreate,
    db: Session = Depends(get_db),
) -> WebhookEventResponse:
    """Process a payment provider webhook event.

    - Validates schema (event_id, payment_reference, status must be SUCCESS|FAILED).
    - Returns ALREADY_PROCESSED for duplicate ``event_id`` values.
    - Atomically updates payment status, booking status, and webhook event record.
    - Safe under concurrent duplicate delivery via database UNIQUE(event_id).
    """
    return webhook_service.process_webhook(db=db, event_in=event_in)
