"""FastAPI dependencies for authentication, authorization, and database access."""

from collections.abc import Callable

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ForbiddenException,
    InvalidTokenException,
    TokenExpiredException,
)
from app.core.security import decode_access_token
from app.db.database import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository

security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    auth_header: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate the JWT Bearer token, returning the authenticated User.

    Raises:
        InvalidTokenException: If Authorization header is missing, malformed, or token invalid.
        TokenExpiredException: If token exp claim has elapsed.
        ForbiddenException: If user account is inactive.
    """
    if not auth_header or not auth_header.credentials:
        raise InvalidTokenException("Missing or malformed Authorization header.")

    token = auth_header.credentials
    try:
        payload = decode_access_token(token)
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise InvalidTokenException("Token payload missing subject.")
        user_id = int(user_id_str)
    except jwt.ExpiredSignatureError as err:
        raise TokenExpiredException("Authentication token has expired.") from err
    except (jwt.PyJWTError, ValueError) as err:
        raise InvalidTokenException("Invalid or corrupted authentication token.") from err

    user = UserRepository.get_by_id(db, user_id=user_id)
    if not user:
        raise InvalidTokenException("User associated with this token no longer exists.")

    if not user.is_active:
        raise ForbiddenException("User account is inactive.")

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure the authenticated user is active."""
    if not current_user.is_active:
        raise ForbiddenException("User account is inactive.")
    return current_user


def require_role(*roles: UserRole) -> Callable[[User], User]:
    """Dependency factory enforcing role-based access control (RBAC).

    Args:
        *roles: One or more UserRole enum values permitted to access the route.

    Returns:
        Dependency callable returning the authenticated user if authorized.
    """
    def role_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in roles:
            allowed = [r.value for r in roles]
            raise ForbiddenException(
                f"Action requires one of the following roles: {allowed}"
            )
        return current_user

    return role_checker
