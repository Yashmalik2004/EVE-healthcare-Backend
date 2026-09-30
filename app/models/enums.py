"""Application-wide enumeration types.

Using ``enum.StrEnum`` (Python 3.11+) so that enum members compare equal to
their string values, which simplifies JSON serialisation and database storage
when ``native_enum=False`` is used with SQLAlchemy.
"""

import enum


class UserRole(enum.StrEnum):
    """Roles assignable to a user account."""

    PATIENT = "PATIENT"
    ADMIN = "ADMIN"


class BookingStatus(enum.StrEnum):
    """Lifecycle states of a diagnostic booking.

    State transitions:
        PENDING  ->  CONFIRMED  (payment succeeded)
        PENDING  ->  FAILED     (payment failed)
        CONFIRMED -> CANCELLED  (user cancels)
    """

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(enum.StrEnum):
    """Processing states of a payment attempt."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
