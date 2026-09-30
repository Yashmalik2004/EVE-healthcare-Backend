"""DiagnosticTest ORM model.

Represents a type of diagnostic test offered by the healthcare network
(e.g. "Complete Blood Count", "Lipid Profile").  The same test can be
offered by multiple centres at different prices, recorded via ``CentreTest``.

Relationships
-------------
- centre_tests : one-to-many  →  CentreTest
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.centre_test import CentreTest



class DiagnosticTest(Base):
    """A type of diagnostic test in the catalogue."""

    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Grouping category e.g. "Haematology", "Biochemistry", "Radiology"
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
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
        "CentreTest", back_populates="test", cascade="all, delete-orphan"
    )

