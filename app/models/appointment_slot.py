"""AppointmentSlot ORM model.

Represents an available time-slot at a diagnostic centre for a particular
centre-test offering.  Once a booking is confirmed, ``is_available`` is set
to False and the slot becomes locked.

Relationships
-------------
- centre  : many-to-one  →  DiagnosticCentre
- booking : one-to-one   →  Booking  (nullable; None if slot is still free)
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AppointmentSlot(Base):
    """A time-slot at a centre for a specific centre-test offering."""

    __tablename__ = "appointment_slots"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    centre_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("diagnostic_centres.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional: slot may be tied to a specific test offering at this centre.
    # NULL means the slot is general-purpose (can be assigned to any test).
    centre_test_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("centre_tests.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    appointment_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    is_available: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    centre: Mapped["DiagnosticCentre"] = relationship(  # noqa: F821
        "DiagnosticCentre", back_populates="slots"
    )
    # uselist=False → one-to-one on the "one" side (Booking holds the FK)
    booking: Mapped["Booking | None"] = relationship(  # noqa: F821
        "Booking", back_populates="appointment_slot", uselist=False
    )
