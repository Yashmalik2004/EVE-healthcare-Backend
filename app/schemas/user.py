"""User Pydantic schemas — request/response models for user-related endpoints.

Security notes
--------------
* ``UserCreate.role`` is intentionally hidden from the public API — the
  field exists internally but the signup endpoint forces ``PATIENT`` regardless
  of what the client sends.  See ``AuthService.register_user``.
* ``UserResponse`` never includes ``password_hash`` — this is enforced by
  the schema definition (only safe fields are listed).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole


class UserBase(BaseModel):
    """Shared fields for user input/output schemas."""

    email: EmailStr = Field(..., description="User email address")
    full_name: str = Field(
        ..., min_length=2, max_length=255, description="Full name of the user"
    )


class UserCreate(UserBase):
    """Schema for user registration requests.

    The ``role`` field is deliberately excluded from OpenAPI docs and must not
    be populated by the public signup endpoint — ``AuthService`` always forces
    ``PATIENT`` for public signups.
    """

    password: str = Field(
        ...,
        min_length=8,
        max_length=100,
        description=(
            "Plaintext password (8–100 characters). "
            "Must include letters and at least one digit or special character."
        ),
    )
    # Role is an internal-only field; not exposed in public-facing OpenAPI docs
    role: UserRole = Field(default=UserRole.PATIENT, exclude=True)


class UserResponse(UserBase):
    """Schema for user data returned in API responses.

    Never includes password_hash or any other sensitive credential.
    """

    id: int
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
