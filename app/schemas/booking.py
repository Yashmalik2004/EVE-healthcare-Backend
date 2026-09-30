"""Booking Pydantic schemas — request and response models."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BookingStatus
from app.schemas.centre_test import CentreTestResponse
from app.schemas.slot import SlotResponse
from app.schemas.user import UserResponse


class BookingCreate(BaseModel):
    """Schema for initiating a new booking."""

    centre_test_id: int = Field(..., ge=1, description="ID of the CentreTest offering to book")
    appointment_slot_id: int = Field(..., ge=1, description="ID of the AppointmentSlot to reserve")


class BookingResponse(BaseModel):
    """Schema for booking details returned in API responses."""

    id: int
    booking_reference: str
    user_id: int
    centre_test_id: int
    appointment_slot_id: int
    amount: Decimal
    status: BookingStatus
    created_at: datetime
    updated_at: datetime
    user: UserResponse | None = None
    centre_test: CentreTestResponse | None = None
    appointment_slot: SlotResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class BookingCancelResponse(BaseModel):
    """Response returned upon successful booking cancellation."""

    id: int
    booking_reference: str
    status: BookingStatus
    message: str = "Booking cancelled successfully."
