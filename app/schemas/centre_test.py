"""CentreTest Pydantic schemas — association between centres and tests with pricing."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.diagnostic_test import DiagnosticTestResponse


class CentreTestCreate(BaseModel):
    """Schema for associating a diagnostic test with a centre and setting its price."""

    test_id: int = Field(..., ge=1, description="ID of the diagnostic test to offer")
    price: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        decimal_places=2,
        max_digits=10,
        description="Centre-specific price in Decimal",
    )
    is_available: bool = Field(default=True, description="Whether test is currently offered")


class CentreTestResponse(BaseModel):
    """Schema for centre test details returned in API responses."""

    id: int
    centre_id: int
    test_id: int
    price: Decimal
    is_available: bool
    created_at: datetime
    updated_at: datetime
    test: DiagnosticTestResponse | None = None

    model_config = ConfigDict(from_attributes=True)
