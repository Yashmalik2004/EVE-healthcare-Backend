"""Booking ORM model.

Captures a patient's confirmed intent to attend a diagnostic appointment.
The ``amount`` column stores a price snapshot taken at booking time from
``CentreTest.price``, so historical records remain accurate even if the
centre later changes pricing.

Status lifecycle:
    PENDING  →  CONFIRMED  (payment succeeded)
    PENDING  →  FAILED     (payment failed)
    CONFIRMED → CANCELLED  (user request)

Relationships
-------------
- user             : many-to-one  →  User
- centre_test      : many-to-one  →  CentreTest
- appointment_slot : many-to-one  →  AppointmentSlot (one-to-one in practice)
- payments         : one-to-many  →  Payment
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.enums import BookingStatus


class Booking(Base):
    """A patient's diagnostic test booking."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    # Externally visible, human-friendly reference (e.g. "EVE-20260930-XXXX")
    booking_reference: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    centre_test_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("centre_tests.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    appointment_slot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("appointment_slots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Price snapshot at booking time — Numeric prevents float rounding errors
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status", native_enum=False),
        default=BookingStatus.PENDING,
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="bookings")  # noqa: F821
    centre_test: Mapped["CentreTest"] = relationship(  # noqa: F821
        "CentreTest", back_populates="bookings"
    )
    appointment_slot: Mapped["AppointmentSlot"] = relationship(  # noqa: F821
        "AppointmentSlot", back_populates="booking"
    )
    payments: Mapped[list["Payment"]] = relationship(  # noqa: F821
        "Payment", back_populates="booking", cascade="all, delete-orphan"
    )
