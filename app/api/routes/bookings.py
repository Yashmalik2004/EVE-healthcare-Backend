"""Bookings API routes."""

from collections.abc import Sequence

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.rate_limit import rate_limit_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.booking import (
    BookingCancelResponse,
    BookingCreate,
    BookingResponse,
)
from app.services.booking_service import booking_service

router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"],
    dependencies=[Depends(rate_limit_user(requests=60, window=60, scope="api:general"))],
)



@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create diagnostic test booking",
    description="Creates a new diagnostic booking in PENDING state with atomic row-level slot reservation.",
)
def create_booking(
    booking_in: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> BookingResponse:
    """Create a new booking and reserve the appointment slot."""
    booking = booking_service.create_booking(db, current_user, booking_in)
    return BookingResponse.model_validate(booking)


@router.get(
    "",
    response_model=list[BookingResponse],
    status_code=status.HTTP_200_OK,
    summary="List bookings",
    description="Returns bookings for the authenticated user, or all bookings for administrators.",
)
def list_bookings(
    skip: int = Query(default=0, ge=0, description="Items to skip"),
    limit: int = Query(default=100, ge=1, le=100, description="Items to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Sequence[BookingResponse]:
    """List bookings belonging to current user (or all if admin)."""
    bookings = booking_service.list_bookings(db, current_user, skip=skip, limit=limit)
    return [BookingResponse.model_validate(b) for b in bookings]


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    status_code=status.HTTP_200_OK,
    summary="Get booking details",
    description="Fetches full details of a specific booking belonging to the authenticated user.",
)
def get_booking(
    booking_id: int = Path(..., ge=1, description="Booking ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> BookingResponse:
    """Retrieve booking by ID (enforces ownership check, returns 403 if unauthorized)."""
    booking = booking_service.get_booking(db, current_user, booking_id)
    return BookingResponse.model_validate(booking)


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel booking",
    description="Cancels an active or pending booking and releases the appointment slot.",
)
def cancel_booking(
    booking_id: int = Path(..., ge=1, description="Booking ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> BookingCancelResponse:
    """Cancel booking and free up the slot."""
    booking = booking_service.cancel_booking(db, current_user, booking_id)
    return BookingCancelResponse(
        id=booking.id,
        booking_reference=booking.booking_reference,
        status=booking.status,
        message="Booking cancelled successfully.",
    )
