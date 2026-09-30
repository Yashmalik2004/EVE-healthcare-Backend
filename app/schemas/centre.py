"""DiagnosticCentre Pydantic schemas — request and response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CentreBase(BaseModel):
    """Base fields for diagnostic centre."""

    name: str = Field(..., min_length=1, max_length=255, description="Centre name")
    address: str = Field(..., min_length=1, max_length=500, description="Physical address")
    city: str = Field(..., min_length=1, max_length=100, description="City")
    state: str = Field(..., min_length=1, max_length=100, description="State")
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0, description="GPS Latitude")
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0, description="GPS Longitude")

    @field_validator("name", "address", "city", "state", mode="after")
    @classmethod
    def validate_non_whitespace(cls, v: str) -> str:
        """Reject empty or whitespace-only strings."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or whitespace only.")
        return stripped


class CentreCreate(CentreBase):
    """Schema for registering a new diagnostic centre."""

    is_active: bool = Field(default=True, description="Whether centre is active")


class CentreUpdate(BaseModel):
    """Schema for updating diagnostic centre fields."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = Field(default=None, min_length=1, max_length=100)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    is_active: bool | None = None

    @field_validator("name", "address", "city", "state", mode="after")
    @classmethod
    def validate_update_non_whitespace(cls, v: str | None) -> str | None:
        """Reject empty or whitespace-only update strings if provided."""
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("Field cannot be empty or whitespace only.")
            return stripped
        return v


class CentreResponse(CentreBase):
    """Schema for centre details returned in API responses."""

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
