"""Authentication business logic service.

Coordinates user registration, credential verification, and JWT generation.
Adheres to the service layer pattern — no raw SQL queries or HTTP details live here.
"""

from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateUserException, InvalidCredentialsException
from app.core.logging import logger
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse, UserLogin
from app.schemas.user import UserCreate, UserResponse


class AuthService:
    """Service handling user registration, authentication, and token creation."""

    def __init__(self, user_repo: type[UserRepository] = UserRepository):
        self.user_repo = user_repo

    def register_user(self, db: Session, user_in: UserCreate) -> User:
        """Register a new patient account with a hashed password.

        Args:
            db: Database session.
            user_in: Validated user creation data.

        Returns:
            Newly created User model instance.

        Raises:
            DuplicateUserException: If email is already in use.
        """
        normalized_email = user_in.email.lower().strip()
        logger.info(f"Attempting user registration for email: {normalized_email}")

        existing = self.user_repo.get_by_email(db, normalized_email)
        if existing:
            logger.warning(f"Registration conflict: email '{normalized_email}' already exists")
            raise DuplicateUserException("A user with this email address already exists.")

        password_hash = get_password_hash(user_in.password)
        # Always force PATIENT role for public registration to prevent privilege escalation
        user = self.user_repo.create(
            db,
            email=normalized_email,
            password_hash=password_hash,
            full_name=user_in.full_name.strip(),
            role=UserRole.PATIENT,
        )
        logger.info(f"User created successfully with id={user.id}")
        return user

    def authenticate_user(self, db: Session, credentials: UserLogin) -> User:
        """Authenticate user by email and password.

        Args:
            db: Database session.
            credentials: Login credentials containing email and password.

        Returns:
            The authenticated User model instance.

        Raises:
            InvalidCredentialsException: If user not found, password incorrect, or account inactive.
        """
        normalized_email = credentials.email.lower().strip()
        user = self.user_repo.get_by_email(db, normalized_email)

        if not user:
            logger.warning(f"Authentication failed: user '{normalized_email}' not found")
            raise InvalidCredentialsException("Invalid email or password.")

        if not verify_password(credentials.password, user.password_hash):
            logger.warning(f"Authentication failed: incorrect password for '{normalized_email}'")
            raise InvalidCredentialsException("Invalid email or password.")

        if not user.is_active:
            logger.warning(f"Authentication failed: inactive account for '{normalized_email}'")
            raise InvalidCredentialsException("User account is inactive.")

        logger.info(f"User id={user.id} authenticated successfully")
        return user

    def create_token_response(self, user: User) -> TokenResponse:
        """Generate JWT access token and return token response envelope."""
        token_payload = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value,
        }
        access_token = create_access_token(token_payload)
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )


auth_service = AuthService()
