"""DiagnosticCentre ORM model.

A physical location that offers one or more diagnostic tests.  The available
tests at a centre (along with centre-specific pricing) are recorded in the
``CentreTest`` join table.

Relationships
-------------
- centre_tests : one-to-many  →  CentreTest
- slots        : one-to-many  →  AppointmentSlot
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.appointment_slot import AppointmentSlot
    from app.models.centre_test import CentreTest



class DiagnosticCentre(Base):
    """A diagnostic testing centre / clinic."""

    __tablename__ = "diagnostic_centres"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    # Optional GPS coordinates for location-aware queries
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    centre_tests: Mapped[list["CentreTest"]] = relationship(
        "CentreTest", back_populates="centre", cascade="all, delete-orphan"
    )
    slots: Mapped[list["AppointmentSlot"]] = relationship(
        "AppointmentSlot", back_populates="centre", cascade="all, delete-orphan"
    )

