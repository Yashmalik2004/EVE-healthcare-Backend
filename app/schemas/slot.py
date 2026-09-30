"""AppointmentSlot Pydantic schemas — request and response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SlotCreate(BaseModel):
    """Schema for creating a new appointment slot at a centre."""

    centre_test_id: int | None = Field(
        default=None, ge=1, description="Optional specific centre-test offering ID"
    )
    appointment_datetime: datetime = Field(
        ..., description="UTC date and time of the appointment slot"
    )
    is_available: bool = Field(default=True, description="Availability flag for booking")


class SlotResponse(BaseModel):
    """Schema for appointment slot returned in API responses."""

    id: int
    centre_id: int
    centre_test_id: int | None = None
    appointment_datetime: datetime
    is_available: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
