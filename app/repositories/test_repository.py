"""DiagnosticTest data access layer."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.diagnostic_test import DiagnosticTest
from app.schemas.diagnostic_test import DiagnosticTestCreate


class TestRepository:
    """Repository handling database operations for diagnostic tests."""

    @staticmethod
    def get_by_id(db: Session, test_id: int) -> DiagnosticTest | None:
        """Fetch a diagnostic test by ID or return None."""
        return db.scalar(select(DiagnosticTest).where(DiagnosticTest.id == test_id))

    @staticmethod
    def list_tests(
        db: Session,
        category: str | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[DiagnosticTest]:
        """Query diagnostic tests with optional category and active filtering and pagination."""
        query = select(DiagnosticTest)
        if category:
            query = query.where(DiagnosticTest.category.ilike(f"%{category.strip()}%"))
        if is_active is not None:
            query = query.where(DiagnosticTest.is_active == is_active)
        return db.scalars(query.offset(skip).limit(limit)).all()

    @staticmethod
    def create(db: Session, test_in: DiagnosticTestCreate) -> DiagnosticTest:
        """Create and persist a new diagnostic test entry."""
        test = DiagnosticTest(
            name=test_in.name.strip(),
            description=test_in.description.strip() if test_in.description else None,
            category=test_in.category.strip(),
            is_active=test_in.is_active,
        )
        db.add(test)
        db.commit()
        db.refresh(test)
        return test
