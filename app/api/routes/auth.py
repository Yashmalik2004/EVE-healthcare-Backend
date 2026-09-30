"""Authentication API routes — registration, login, and user profile."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.rate_limit import rate_limit_ip, rate_limit_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse, UserLogin
from app.schemas.user import UserCreate, UserResponse
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_ip(requests=3, window=60, scope="auth:signup"))],
    summary="Register a new user",
    description="Registers a new patient account with a securely hashed password.",
)

def signup(user_in: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    """Register a new user with PATIENT role."""
    user = auth_service.register_user(db, user_in)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_ip(requests=5, window=60, scope="auth:login"))],
    summary="User login",
    description="Authenticates credentials and returns a signed JWT access token.",
)
def login(credentials: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate with email and password, issuing a JWT."""
    user = auth_service.authenticate_user(db, credentials)
    return auth_service.create_token_response(user)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit_user(requests=60, window=60, scope="api:general"))],
    summary="Get current user profile",
    description="Returns the profile of the currently authenticated active user.",
)
def get_me(current_user: User = Depends(get_current_active_user)) -> UserResponse:
    """Return profile for the bearer token subject."""
    return UserResponse.model_validate(current_user)

