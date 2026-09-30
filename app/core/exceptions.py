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


# ── Generic Resource Exceptions ─────────────────────────────────────────────

class NotFoundException(AppException):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource: str, identifier: Any, code: str | None = None):
        error_code = code or f"{resource.upper()}_NOT_FOUND"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code=error_code,
            message=f"{resource} with identifier '{identifier}' was not found.",
        )


class BadRequestException(AppException):
    def __init__(self, code: str, message: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=code,
            message=message,
        )


class ConflictException(AppException):
    def __init__(self, code: str, message: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code=code,
            message=message,
        )


class ValidationException(AppException):
    def __init__(self, code: str, message: str, details: Any | None = None):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=code,
            message=message,
            details=details,
        )


# ── Authentication & Authorization Domain Exceptions ────────────────────────

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


# ── Domain-Specific Named Exceptions ────────────────────────────────────────

class BookingNotFoundException(NotFoundException):
    def __init__(self, identifier: Any):
        super().__init__("Booking", identifier, code="BOOKING_NOT_FOUND")


class CentreNotFoundException(NotFoundException):
    def __init__(self, identifier: Any):
        super().__init__("DiagnosticCentre", identifier, code="DIAGNOSTICCENTRE_NOT_FOUND")


class TestNotFoundException(NotFoundException):
    def __init__(self, identifier: Any):
        super().__init__("DiagnosticTest", identifier, code="DIAGNOSTICTEST_NOT_FOUND")


class SlotNotFoundException(NotFoundException):
    def __init__(self, identifier: Any):
        super().__init__("AppointmentSlot", identifier, code="APPOINTMENTSLOT_NOT_FOUND")


class PaymentNotFoundException(NotFoundException):
    def __init__(self, identifier: Any):
        super().__init__("Payment", identifier, code="PAYMENT_NOT_FOUND")


class SlotAlreadyBookedException(ConflictException):
    def __init__(self, message: str = "Appointment slot is already booked."):
        super().__init__(code="SLOT_ALREADY_BOOKED", message=message)


class InvalidStateTransitionException(ConflictException):
    def __init__(self, message: str = "Invalid state transition for resource."):
        super().__init__(code="INVALID_STATE_TRANSITION", message=message)


class PaymentAmountMismatchException(ValidationException):
    def __init__(self, message: str = "Provided payment amount does not match booking amount."):
        super().__init__(code="PAYMENT_AMOUNT_MISMATCH", message=message)


class PaymentAlreadyCompletedException(ConflictException):
    def __init__(self, message: str = "Payment has already been completed for this booking."):
        super().__init__(code="PAYMENT_ALREADY_COMPLETED", message=message)


class BookingAlreadyCancelledException(ConflictException):
    def __init__(self, message: str = "Booking has already been cancelled."):
        super().__init__(code="BOOKING_ALREADY_CANCELLED", message=message)


class WebhookAlreadyProcessedException(ConflictException):
    def __init__(self, message: str = "Webhook event has already been processed."):
        super().__init__(code="WEBHOOK_ALREADY_PROCESSED", message=message)
