"""Payments API routes.

Implements:
    POST /payments                 — Initiate a simulated payment
    GET  /payments/{payment_id}    — Retrieve a payment record

The ``Idempotency-Key`` header is optional but strongly recommended for
POST requests to prevent duplicate charges on network retries.
"""

from fastapi import APIRouter, Depends, Header, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.rate_limit import rate_limit_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.payment import PaymentCreate, PaymentResponse
from app.services.payment_service import payment_service

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_user(requests=10, window=60, scope="payments:create"))],
    summary="Process a simulated payment",

    description=(
        "Processes a simulated payment for a PENDING booking. "
        "Provide an optional `Idempotency-Key` header to safely retry "
        "without creating duplicate records."
    ),
)
def create_payment(
    payment_in: PaymentCreate,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Optional client-supplied deduplication key for safe retries.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PaymentResponse:
    """Initiate a simulated payment.

    - Validates booking ownership and current status.
    - Verifies the supplied amount matches the snapshotted booking amount.
    - Transitions the booking to CONFIRMED (success) or FAILED.
    - Returns the same payment record on repeated requests with the same
      ``Idempotency-Key``.
    """
    payment = payment_service.process_payment(
        db=db,
        user=current_user,
        payment_in=payment_in,
        idempotency_key=idempotency_key,
    )
    return PaymentResponse.model_validate(payment)


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_user(requests=60, window=60, scope="api:general"))],
    summary="Retrieve a payment record",

    description="Fetches a payment record by ID. Only the booking owner or an admin may view it.",
)
def get_payment(
    payment_id: int = Path(..., ge=1, description="Payment ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PaymentResponse:
    """Return payment details (enforces ownership; returns 403 if unauthorized)."""
    payment = payment_service.get_payment(db=db, user=current_user, payment_id=payment_id)
    return PaymentResponse.model_validate(payment)
