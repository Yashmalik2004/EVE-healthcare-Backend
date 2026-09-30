"""Auth Pydantic schemas — login request and token response."""

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserResponse


class UserLogin(BaseModel):
    """Credentials for login endpoint."""

    email: EmailStr = Field(..., description="Registered email address")
    password: str = Field(..., min_length=1, description="Account password")


class TokenResponse(BaseModel):
    """Response returned on successful login."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenPayload(BaseModel):
    """Internal model for decoding JWT payload claims."""

    sub: str | None = None
    email: str | None = None
    role: str | None = None
    exp: int | None = None
    iat: int | None = None
