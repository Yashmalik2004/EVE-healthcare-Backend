"""Application-level exception hierarchy.

All custom exceptions extend AppException so the global handler in main.py
can serialise them into a consistent error envelope:

    {
        "success": false,
        "error": {
            "code": "SOME_CODE",
            "message": "Human-readable description.",
            "details": <optional>
        }
    }

New domain exceptions introduced in later phases should be added here.
"""

from typing import Any

from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base application exception with structured error code and response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message
        self.details = details


# ── Generic Resource ────────────────────────────────────────────────────────

class NotFoundException(AppException):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource: str, identifier: Any):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code=f"{resource.upper()}_NOT_FOUND",
            message=f"{resource} with identifier '{identifier}' was not found.",
        )


# ── Authentication & Authorization ──────────────────────────────────────────
# NOTE: These are placeholder exception classes.
# Full JWT implementation is deferred to the authentication phase.

class InvalidCredentialsException(AppException):
    def __init__(self, message: str = "Invalid email or password."):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CREDENTIALS",
            message=message,
            headers={"WWW-Authenticate": "Bearer"},
        )


class TokenExpiredException(AppException):
    def __init__(self, message: str = "Token has expired."):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="TOKEN_EXPIRED",
            message=message,
            headers={"WWW-Authenticate": "Bearer"},
        )


class InvalidTokenException(AppException):
    def __init__(self, message: str = "Invalid or malformed authentication token."):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_TOKEN",
            message=message,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenException(AppException):
    def __init__(self, message: str = "You do not have permission to perform this action."):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            code="FORBIDDEN",
            message=message,
        )


class DuplicateUserException(AppException):
    def __init__(self, message: str = "A user with this email already exists."):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code="DUPLICATE_USER",
            message=message,
        )


# ── Business Validation ──────────────────────────────────────────────────────

class ValidationException(AppException):
    def __init__(self, code: str, message: str, details: Any | None = None):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=code,
            message=message,
            details=details,
        )


class ConflictException(AppException):
    def __init__(self, code: str, message: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code=code,
            message=message,
        )


class BadRequestException(AppException):
    def __init__(self, code: str, message: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=code,
            message=message,
        )
