"""CentreTest ORM model.

Association table between DiagnosticCentre and DiagnosticTest that carries
the centre-specific price for each test.

The composite unique constraint on (centre_id, test_id) prevents a centre
from offering the same test at two different prices simultaneously.

Relationships
-------------
- centre   : many-to-one  →  DiagnosticCentre
- test     : many-to-one  →  DiagnosticTest
- bookings : one-to-many  →  Booking
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.booking import Booking
    from app.models.centre import DiagnosticCentre
    from app.models.diagnostic_test import DiagnosticTest



class CentreTest(Base):
    """A diagnostic test offered by a specific centre at a specific price."""

    __tablename__ = "centre_tests"
    __table_args__ = (
        # A centre can only offer a given test once (at one price at a time)
        UniqueConstraint("centre_id", "test_id", name="uq_centre_test"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    centre_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("diagnostic_centres.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("diagnostic_tests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Precise decimal representation — never float for monetary values
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    centre: Mapped["DiagnosticCentre"] = relationship(
        "DiagnosticCentre", back_populates="centre_tests"
    )
    test: Mapped["DiagnosticTest"] = relationship(
        "DiagnosticTest", back_populates="centre_tests"
    )
    bookings: Mapped[list["Booking"]] = relationship(
        "Booking", back_populates="centre_test"
    )

