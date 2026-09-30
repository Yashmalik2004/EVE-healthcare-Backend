"""DiagnosticTest Pydantic schemas — request and response models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DiagnosticTestBase(BaseModel):
    """Base fields for diagnostic test catalogue entries."""

    name: str = Field(..., min_length=1, max_length=255, description="Test name")
    description: str | None = Field(default=None, description="Detailed test description")
    category: str = Field(..., min_length=1, max_length=100, description="Category (e.g. Hematology)")

    @field_validator("name", "category", mode="after")
    @classmethod
    def validate_non_whitespace(cls, v: str) -> str:
        """Reject empty or whitespace-only strings."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or whitespace only.")
        return stripped


class DiagnosticTestCreate(DiagnosticTestBase):
    """Schema for creating a new diagnostic test."""

    is_active: bool = Field(default=True, description="Whether test is active")


class DiagnosticTestResponse(DiagnosticTestBase):
    """Schema for diagnostic test details returned in API responses."""

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
